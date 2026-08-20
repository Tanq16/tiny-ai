// Package runner executes the suite's Python scripts as child processes and turns their NDJSON
// output into job state a browser can follow.
package runner

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"sync"
	"time"

	"github.com/tanq16/tiny-ai-suite/internal/catalog"
)

var (
	ErrUnknownTask = errors.New("unknown task")
	ErrJobNotFound = errors.New("unknown job")
	ErrJobFinished = errors.New("job already finished")
	ErrNoArtifact  = errors.New("unknown artifact")
	ErrQueueFull   = errors.New("job queue is full")
)

// ValidationError reports a submission the catalog rejects, which a caller turns into a 400.
type ValidationError struct{ Msg string }

func (e *ValidationError) Error() string { return e.Msg }

const (
	queueCapacity = 256
	deleteGrace   = 5 * time.Second
)

type Config struct {
	DataDir    string
	ScriptsDir string
	Workers    int
}

type Upload struct {
	Param    string
	Filename string
	Content  io.Reader
}

type Submission struct {
	TaskID string
	Values map[string]string
	Files  []Upload
}

type Runner struct {
	scriptsDir string
	jobsDir    string
	workers    int

	queue chan *record
	wg    sync.WaitGroup

	ctx    context.Context
	cancel context.CancelFunc

	mu   sync.RWMutex
	jobs map[string]*record
}

// New prepares the data directory and reloads the jobs already on disk.
func New(cfg Config) (*Runner, error) {
	dataDir, err := filepath.Abs(cfg.DataDir)
	if err != nil {
		return nil, err
	}
	scriptsDir, err := filepath.Abs(cfg.ScriptsDir)
	if err != nil {
		return nil, err
	}
	jobsDir := filepath.Join(dataDir, "jobs")
	if err := os.MkdirAll(jobsDir, 0o755); err != nil {
		return nil, err
	}

	ctx, cancel := context.WithCancel(context.Background())
	r := &Runner{
		scriptsDir: scriptsDir,
		jobsDir:    jobsDir,
		workers:    max(cfg.Workers, 1),
		queue:      make(chan *record, queueCapacity),
		ctx:        ctx,
		cancel:     cancel,
		jobs:       make(map[string]*record),
	}
	if err := r.reload(); err != nil {
		cancel()
		return nil, err
	}
	return r, nil
}

func (r *Runner) Start() {
	for range r.workers {
		r.wg.Go(r.worker)
	}
}

// Stop kills every running child and waits for the workers to unwind.
func (r *Runner) Stop() {
	r.cancel()
	r.wg.Wait()
}

func (r *Runner) worker() {
	for {
		select {
		case <-r.ctx.Done():
			return
		case rec := <-r.queue:
			r.dispatch(rec)
		}
	}
}

func (r *Runner) dispatch(rec *record) {
	task, err := catalog.Get(rec.snap.Task)
	if err != nil {
		rec.fail(err.Error())
		return
	}
	values, files := rec.submitted()
	r.execute(rec, task, values, files)
}

func (r *Runner) jobContext(rec *record) (context.Context, context.CancelFunc) {
	ctx, cancel := context.WithCancel(r.ctx)
	rec.mu.Lock()
	rec.cancel = cancel
	canceled := rec.canceled
	rec.mu.Unlock()
	if canceled {
		cancel()
	}
	return ctx, cancel
}

func (r *Runner) Submit(sub Submission) (Job, error) {
	task, err := catalog.Get(sub.TaskID)
	if err != nil {
		return Job{}, fmt.Errorf("%w: %s", ErrUnknownTask, sub.TaskID)
	}

	id := newJobID()
	dir := filepath.Join(r.jobsDir, id)
	inputDir := filepath.Join(dir, "input")
	outDir := filepath.Join(dir, "output")
	if err := os.MkdirAll(inputDir, 0o755); err != nil {
		return Job{}, err
	}
	if err := os.MkdirAll(outDir, 0o755); err != nil {
		return Job{}, err
	}

	values := make(map[string]string, len(sub.Values))
	for k, v := range sub.Values {
		values[k] = v
	}
	files := make(map[string]string, len(sub.Files))
	inputs := make([]Input, 0, len(sub.Files))
	for _, up := range sub.Files {
		name := sanitizeFilename(up.Filename)
		dest := filepath.Join(inputDir, name)
		size, err := saveUpload(dest, up.Content)
		if err != nil {
			os.RemoveAll(dir)
			return Job{}, err
		}
		files[up.Param] = dest
		inputs = append(inputs, Input{Param: up.Param, Filename: name, Bytes: size})
	}
	slices.SortFunc(inputs, func(a, b Input) int { return strings.Compare(a.Param, b.Param) })

	if err := validate(task, values, files); err != nil {
		os.RemoveAll(dir)
		return Job{}, err
	}

	rec := &record{
		snap: Job{
			ID:        id,
			Task:      task.ID,
			Title:     task.Title,
			State:     StateQueued,
			CreatedAt: stamp(),
			Params:    values,
			Inputs:    inputs,
			Artifacts: []Artifact{},
		},
		subs:   make(map[chan Event]struct{}),
		done:   make(chan struct{}),
		dir:    dir,
		outDir: outDir,
		files:  files,
	}
	rec.mu.Lock()
	rec.publishLocked(Event{Event: EventState, State: StateQueued})
	rec.persistLocked()
	snap := rec.snapshotLocked(false)
	rec.mu.Unlock()

	r.mu.Lock()
	r.jobs[id] = rec
	r.mu.Unlock()

	select {
	case r.queue <- rec:
	default:
		rec.fail(ErrQueueFull.Error())
		return snap, ErrQueueFull
	}
	return snap, nil
}

func saveUpload(dest string, src io.Reader) (int64, error) {
	f, err := os.OpenFile(dest, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o600)
	if err != nil {
		return 0, err
	}
	defer f.Close()
	return io.Copy(f, src)
}

func newJobID() string {
	var b [3]byte
	rand.Read(b[:])
	return time.Now().Format("20060102-150405") + "-" + hex.EncodeToString(b[:])
}

func (r *Runner) lookup(id string) (*record, bool) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	rec, ok := r.jobs[id]
	return rec, ok
}

// List returns every job newest first.
func (r *Runner) List() []Job {
	r.mu.RLock()
	recs := make([]*record, 0, len(r.jobs))
	for _, rec := range r.jobs {
		recs = append(recs, rec)
	}
	r.mu.RUnlock()

	jobs := make([]Job, 0, len(recs))
	for _, rec := range recs {
		jobs = append(jobs, rec.snapshot(false))
	}
	slices.SortFunc(jobs, func(a, b Job) int {
		if c := b.CreatedAt.Compare(a.CreatedAt); c != 0 {
			return c
		}
		return strings.Compare(b.ID, a.ID)
	})
	return jobs
}

func (r *Runner) Get(id string, withEvents bool) (Job, error) {
	rec, ok := r.lookup(id)
	if !ok {
		return Job{}, ErrJobNotFound
	}
	return rec.snapshot(withEvents), nil
}

func (r *Runner) Subscribe(id string, from int) (*Subscription, error) {
	rec, ok := r.lookup(id)
	if !ok {
		return nil, ErrJobNotFound
	}
	return rec.subscribe(from), nil
}

func (r *Runner) Cancel(id string) error {
	rec, ok := r.lookup(id)
	if !ok {
		return ErrJobNotFound
	}
	rec.mu.Lock()
	if rec.snap.State.Terminal() {
		rec.mu.Unlock()
		return ErrJobFinished
	}
	rec.canceled = true
	cancel := rec.cancel
	rec.mu.Unlock()

	if cancel == nil {
		rec.transition(StateCanceled)
		return nil
	}
	cancel()
	return nil
}

// Delete stops the job if it is still live and removes its directory along with its history.
func (r *Runner) Delete(id string) error {
	rec, ok := r.lookup(id)
	if !ok {
		return ErrJobNotFound
	}
	if err := r.Cancel(id); err != nil && !errors.Is(err, ErrJobFinished) {
		return err
	}
	select {
	case <-rec.done:
	case <-time.After(deleteGrace):
	}

	r.mu.Lock()
	delete(r.jobs, id)
	r.mu.Unlock()
	return os.RemoveAll(rec.dir)
}

// ArtifactPath resolves a served artifact name inside the job's output directory, rejecting any escape.
func (r *Runner) ArtifactPath(id, name string) (string, error) {
	rec, ok := r.lookup(id)
	if !ok {
		return "", ErrJobNotFound
	}
	if name == "" {
		return "", ErrNoArtifact
	}
	full := filepath.Join(rec.outDir, filepath.FromSlash(name))
	rel, err := filepath.Rel(rec.outDir, full)
	if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
		return "", ErrNoArtifact
	}
	return full, nil
}

func (rec *record) submitted() (map[string]string, map[string]string) {
	rec.mu.Lock()
	defer rec.mu.Unlock()
	values := make(map[string]string, len(rec.snap.Params))
	for k, v := range rec.snap.Params {
		values[k] = v
	}
	files := make(map[string]string, len(rec.files))
	for k, v := range rec.files {
		files[k] = v
	}
	return values, files
}

func (rec *record) persistLocked() {
	snap := rec.snapshotLocked(true)
	data, err := json.MarshalIndent(snap, "", "  ")
	if err == nil {
		tmp := filepath.Join(rec.dir, "job.json.tmp")
		if err = os.WriteFile(tmp, data, 0o600); err == nil {
			err = os.Rename(tmp, filepath.Join(rec.dir, "job.json"))
		}
	}
	if err != nil {
		rec.publishLocked(Event{Event: EventLog, Level: "warn", Message: "could not write job.json: " + err.Error()})
	}
}

func (r *Runner) reload() error {
	entries, err := os.ReadDir(r.jobsDir)
	if err != nil {
		return err
	}
	for _, entry := range entries {
		if !entry.IsDir() {
			continue
		}
		dir := filepath.Join(r.jobsDir, entry.Name())
		data, err := os.ReadFile(filepath.Join(dir, "job.json"))
		if err != nil {
			continue
		}
		var snap Job
		if err := json.Unmarshal(data, &snap); err != nil || snap.ID == "" {
			continue
		}
		events := snap.Events
		snap.Events = nil
		if snap.Artifacts == nil {
			snap.Artifacts = []Artifact{}
		}
		rec := &record{
			snap:   snap,
			events: events,
			subs:   make(map[chan Event]struct{}),
			done:   make(chan struct{}),
			dir:    dir,
			outDir: filepath.Join(dir, "output"),
		}
		if len(events) > 0 {
			rec.seq = events[len(events)-1].Seq
		}
		if snap.State.Terminal() {
			close(rec.done)
		} else {
			rec.snap.Error = "interrupted when the server stopped"
			rec.transitionLocked(StateFailed)
		}
		r.jobs[snap.ID] = rec
	}
	return nil
}
