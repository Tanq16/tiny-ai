package runner

import (
	"cmp"
	"io"
	"maps"
	"math"
	"net/url"
	"path"
	"slices"
	"strings"
	"sync"
	"time"
)

type State string

const (
	StateQueued    State = "queued"
	StateRunning   State = "running"
	StateSucceeded State = "succeeded"
	StateFailed    State = "failed"
	StateCanceled  State = "canceled"
)

func (s State) Terminal() bool {
	return s == StateSucceeded || s == StateFailed || s == StateCanceled
}

type Progress struct {
	Fraction float64 `json:"fraction"`
	Message  string  `json:"message"`
}

type Artifact struct {
	Name  string `json:"name"`
	Label string `json:"label"`
	Kind  string `json:"kind"`
	Bytes int64  `json:"bytes"`
	URL   string `json:"url"`
}

type Input struct {
	Param    string `json:"param"`
	Filename string `json:"filename"`
	Bytes    int64  `json:"bytes"`
}

type Job struct {
	ID              string            `json:"id"`
	Task            string            `json:"task"`
	Title           string            `json:"title"`
	State           State             `json:"state"`
	CreatedAt       time.Time         `json:"createdAt"`
	StartedAt       *time.Time        `json:"startedAt"`
	FinishedAt      *time.Time        `json:"finishedAt"`
	Params          map[string]string `json:"params"`
	Inputs          []Input           `json:"inputs"`
	Progress        Progress          `json:"progress"`
	Artifacts       []Artifact        `json:"artifacts"`
	Result          map[string]any    `json:"result"`
	Error           string            `json:"error"`
	DurationSeconds float64           `json:"durationSeconds"`
	Events          []Event           `json:"events,omitzero"`
}

const (
	EventStart    = "start"
	EventLog      = "log"
	EventProgress = "progress"
	EventArtifact = "artifact"
	EventResult   = "result"
	EventDone     = "done"
	EventError    = "error"
	EventState    = "state"
	EventChat     = "chat"
	EventDelta    = "delta"
)

type Event struct {
	Seq       int            `json:"seq"`
	At        time.Time      `json:"at"`
	Event     string         `json:"event"`
	State     State          `json:"state,omitzero"`
	Level     string         `json:"level,omitzero"`
	Fraction  *float64       `json:"fraction,omitzero"`
	Message   string         `json:"message,omitzero"`
	Current   *int           `json:"current,omitzero"`
	Total     *int           `json:"total,omitzero"`
	Path      string         `json:"path,omitzero"`
	Kind      string         `json:"kind,omitzero"`
	Label     string         `json:"label,omitzero"`
	Bytes     *int64         `json:"bytes,omitzero"`
	Data      map[string]any `json:"data,omitzero"`
	Status    string         `json:"status,omitzero"`
	DurationS *float64       `json:"duration_s,omitzero"`
	Traceback string         `json:"traceback,omitzero"`
	Role      string         `json:"role,omitzero"`
	Files     []string       `json:"files,omitzero"`
}

type Subscription struct {
	Backlog []Event
	Events  <-chan Event
	Close   func()
}

const subscriberBuffer = 256

type record struct {
	mu     sync.Mutex
	snap   Job
	events []Event
	subs   map[chan Event]struct{}
	seq    int
	done   chan struct{}

	dir       string
	inDir     string
	outDir    string
	files     map[string]string
	startWall time.Time
	cancel    func()
	canceled  bool

	interactive bool
	sendMu      sync.Mutex
	stdin       io.WriteCloser
	turns       int
}

func stamp() time.Time { return time.Now().UTC().Truncate(time.Second) }

func (rec *record) fanoutLocked(e Event) Event {
	rec.seq++
	e.Seq = rec.seq
	e.At = stamp()
	for ch := range rec.subs {
		select {
		case ch <- e:
		default:
			delete(rec.subs, ch)
			close(ch)
		}
	}
	return e
}

func (rec *record) publishLocked(e Event) {
	rec.events = append(rec.events, rec.fanoutLocked(e))
}

func (rec *record) publish(e Event) {
	rec.mu.Lock()
	defer rec.mu.Unlock()
	rec.publishLocked(e)
}

func (rec *record) closeSubsLocked() {
	for ch := range rec.subs {
		delete(rec.subs, ch)
		close(ch)
	}
}

func (rec *record) transition(state State) {
	rec.mu.Lock()
	defer rec.mu.Unlock()
	rec.transitionLocked(state)
}

func (rec *record) transitionLocked(state State) {
	if rec.snap.State == state || rec.snap.State.Terminal() {
		return
	}
	rec.snap.State = state
	switch {
	case state == StateRunning:
		at := stamp()
		rec.snap.StartedAt = &at
		rec.startWall = time.Now()
	case state.Terminal():
		at := stamp()
		rec.snap.FinishedAt = &at
		if !rec.startWall.IsZero() {
			rec.snap.DurationSeconds = math.Round(time.Since(rec.startWall).Seconds()*1000) / 1000
		}
		if state == StateSucceeded {
			rec.snap.Progress.Fraction = 1
		}
	}
	rec.publishLocked(Event{Event: EventState, State: state})
	rec.persistLocked()
	if state.Terminal() {
		rec.closeSubsLocked()
		select {
		case <-rec.done:
		default:
			close(rec.done)
		}
	}
}

func (rec *record) snapshot(withEvents bool) Job {
	rec.mu.Lock()
	defer rec.mu.Unlock()
	return rec.snapshotLocked(withEvents)
}

func (rec *record) snapshotLocked(withEvents bool) Job {
	out := rec.snap
	out.Params = maps.Clone(rec.snap.Params)
	out.Inputs = slices.Clone(rec.snap.Inputs)
	out.Artifacts = slices.Clone(rec.snap.Artifacts)
	out.Result = maps.Clone(rec.snap.Result)
	if withEvents {
		out.Events = slices.Clone(rec.events)
	} else {
		out.Events = nil
	}
	return out
}

func (rec *record) subscribe(from int) *Subscription {
	rec.mu.Lock()
	defer rec.mu.Unlock()

	backlog := make([]Event, 0, len(rec.events))
	for _, e := range rec.events {
		if e.Seq >= from {
			backlog = append(backlog, e)
		}
	}
	if rec.snap.State.Terminal() {
		return &Subscription{Backlog: backlog, Close: func() {}}
	}
	ch := make(chan Event, subscriberBuffer)
	rec.subs[ch] = struct{}{}
	return &Subscription{
		Backlog: backlog,
		Events:  ch,
		Close:   func() { rec.unsubscribe(ch) },
	}
}

func (rec *record) unsubscribe(ch chan Event) {
	rec.mu.Lock()
	defer rec.mu.Unlock()
	if _, ok := rec.subs[ch]; ok {
		delete(rec.subs, ch)
		close(ch)
	}
}

func (rec *record) apply(e Event) {
	rec.mu.Lock()
	defer rec.mu.Unlock()

	switch e.Event {
	case EventDelta:
		rec.fanoutLocked(e)
		return
	case EventProgress:
		if e.Fraction != nil {
			rec.snap.Progress.Fraction = min(max(*e.Fraction, 0), 1)
		}
		if e.Message != "" {
			rec.snap.Progress.Message = e.Message
		}
	case EventArtifact:
		rec.snap.Artifacts = append(rec.snap.Artifacts, rec.artifactLocked(e))
	case EventResult:
		rec.snap.Result = e.Data
	case EventError:
		if rec.snap.Error == "" {
			rec.snap.Error = e.Message
		}
	}
	rec.publishLocked(e)
	if e.Event == EventChat {
		rec.persistLocked()
	}
}

func (rec *record) artifactLocked(e Event) Artifact {
	name := artifactName(rec.outDir, e.Path)
	var size int64
	if e.Bytes != nil {
		size = *e.Bytes
	}
	return Artifact{
		Name:  name,
		Label: cmp.Or(e.Label, path.Base(name)),
		Kind:  cmp.Or(e.Kind, "other"),
		Bytes: size,
		URL:   artifactURL(rec.snap.ID, name),
	}
}

func artifactURL(id, name string) string {
	segments := strings.Split(name, "/")
	for i, s := range segments {
		segments[i] = url.PathEscape(s)
	}
	return "/api/jobs/" + url.PathEscape(id) + "/artifacts/" + strings.Join(segments, "/")
}
