package runner

import (
	"bufio"
	"encoding/json"
	"fmt"
	"io"
	"maps"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/tanq16/tiny-ai-suite/internal/catalog"
)

const (
	maxLineBytes = 16 << 20
	waitDelay    = 5 * time.Second
)

var scriptEvents = []string{EventStart, EventLog, EventProgress, EventArtifact, EventResult, EventDone, EventError}

func buildArgs(task catalog.Task, projectDir, outDir string, values, files map[string]string) []string {
	args := []string{"run", "--project", projectDir, task.Project, "--json", "--outdir", outDir}
	for _, p := range task.Params {
		flag := "--" + p.Name
		switch p.Type {
		case catalog.ParamFile:
			if path := files[p.Name]; path != "" {
				args = append(args, flag, path)
			}
		case catalog.ParamBool:
			switch {
			case truthy(values[p.Name]):
				args = append(args, flag)
			case p.Default == "true":
				args = append(args, "--no-"+p.Name)
			}
		default:
			if v := values[p.Name]; v != "" {
				args = append(args, flag, v)
			}
		}
	}
	return args
}

func truthy(v string) bool {
	switch strings.ToLower(strings.TrimSpace(v)) {
	case "on", "yes":
		return true
	}
	b, err := strconv.ParseBool(strings.TrimSpace(v))
	return err == nil && b
}

// parseLine degrades anything it does not recognize into a log event, so a stray library print never fails the job.
func parseLine(line string) (Event, bool) {
	if strings.TrimSpace(line) == "" {
		return Event{}, false
	}
	var e Event
	if err := json.Unmarshal([]byte(line), &e); err != nil || !slices.Contains(scriptEvents, e.Event) {
		return Event{Event: EventLog, Level: "info", Message: strings.TrimRight(line, "\r")}, true
	}
	e.Seq = 0
	e.At = time.Time{}
	e.State = ""
	return e, true
}

func validate(task catalog.Task, values, files map[string]string) error {
	for _, name := range slices.Sorted(maps.Keys(values)) {
		p, ok := task.Param(name)
		if !ok {
			return &ValidationError{Msg: fmt.Sprintf("task %q has no parameter %q", task.ID, name)}
		}
		if p.Type == catalog.ParamFile {
			return &ValidationError{Msg: fmt.Sprintf("parameter %q must be sent as a file", name)}
		}
	}
	for _, name := range slices.Sorted(maps.Keys(files)) {
		p, ok := task.Param(name)
		if !ok {
			return &ValidationError{Msg: fmt.Sprintf("task %q has no parameter %q", task.ID, name)}
		}
		if p.Type != catalog.ParamFile {
			return &ValidationError{Msg: fmt.Sprintf("parameter %q is not a file", name)}
		}
	}
	for _, p := range task.Params {
		if !p.Required {
			continue
		}
		if p.Type == catalog.ParamFile {
			if files[p.Name] == "" {
				return &ValidationError{Msg: fmt.Sprintf("parameter %q is required", p.Name)}
			}
			continue
		}
		if strings.TrimSpace(values[p.Name]) == "" {
			return &ValidationError{Msg: fmt.Sprintf("parameter %q is required", p.Name)}
		}
	}
	return nil
}

func sanitizeFilename(name string) string {
	name = strings.Map(func(r rune) rune {
		if r < 0x20 || r == 0x7f || r == '/' || r == '\\' {
			return '_'
		}
		return r
	}, filepath.Base(name))
	name = strings.TrimSpace(name)
	if name == "" || name == "." || name == ".." {
		return "upload"
	}
	return name
}

func artifactName(outDir, reported string) string {
	if reported == "" {
		return ""
	}
	rel, err := filepath.Rel(outDir, filepath.Clean(reported))
	if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
		return filepath.Base(reported)
	}
	return filepath.ToSlash(rel)
}

func killGroup(pid int) error {
	if err := syscall.Kill(-pid, syscall.SIGKILL); err != nil {
		return syscall.Kill(pid, syscall.SIGKILL)
	}
	return nil
}

func (r *Runner) execute(rec *record, task catalog.Task, values, files map[string]string) {
	rec.mu.Lock()
	canceled := rec.canceled
	rec.mu.Unlock()
	if canceled {
		return
	}

	ctx, cancel := r.jobContext(rec)
	defer cancel()

	args := buildArgs(task, filepath.Join(r.scriptsDir, task.Project), rec.outDir, values, files)
	cmd := exec.CommandContext(ctx, "uv", args...)
	cmd.Dir = r.scriptsDir
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	cmd.Cancel = func() error { return killGroup(cmd.Process.Pid) }
	cmd.WaitDelay = waitDelay

	stdout, err := cmd.StdoutPipe()
	if err != nil {
		rec.fail(err.Error())
		return
	}
	stderr, err := cmd.StderrPipe()
	if err != nil {
		rec.fail(err.Error())
		return
	}

	logFile, err := os.OpenFile(filepath.Join(rec.dir, "stderr.log"), os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o600)
	if err != nil {
		rec.fail(err.Error())
		return
	}
	defer logFile.Close()

	if err := cmd.Start(); err != nil {
		rec.fail(fmt.Sprintf("could not start %s: %v", task.Project, err))
		return
	}
	rec.transition(StateRunning)

	var wg sync.WaitGroup
	wg.Go(func() { rec.pumpStdout(stdout) })
	wg.Go(func() { rec.pumpStderr(stderr, logFile) })
	wg.Wait()

	rec.finish(cmd.Wait(), r.ctx.Err() != nil)
}

func (rec *record) pumpStdout(stdout io.Reader) {
	scanner := bufio.NewScanner(stdout)
	scanner.Buffer(make([]byte, 0, 64*1024), maxLineBytes)
	for scanner.Scan() {
		if e, ok := parseLine(scanner.Text()); ok {
			rec.apply(e)
		}
	}
	if err := scanner.Err(); err != nil {
		rec.publish(Event{Event: EventLog, Level: "warn", Message: "stdout closed early: " + err.Error()})
	}
}

func (rec *record) pumpStderr(stderr io.Reader, sink io.Writer) {
	scanner := bufio.NewScanner(stderr)
	scanner.Buffer(make([]byte, 0, 64*1024), maxLineBytes)
	for scanner.Scan() {
		line := scanner.Text()
		fmt.Fprintln(sink, line)
		rec.publish(Event{Event: EventLog, Level: "warn", Message: line})
	}
}

func (rec *record) finish(waitErr error, stopped bool) {
	rec.mu.Lock()
	switch {
	case rec.canceled || stopped:
		rec.mu.Unlock()
		rec.transition(StateCanceled)
		return
	case rec.snap.Error != "":
		rec.mu.Unlock()
		rec.transition(StateFailed)
		return
	case waitErr != nil:
		rec.snap.Error = waitErr.Error()
		rec.mu.Unlock()
		rec.transition(StateFailed)
		return
	}
	rec.mu.Unlock()
	rec.transition(StateSucceeded)
}

func (rec *record) fail(reason string) {
	rec.mu.Lock()
	if rec.snap.Error == "" {
		rec.snap.Error = reason
	}
	rec.mu.Unlock()
	rec.transition(StateFailed)
}
