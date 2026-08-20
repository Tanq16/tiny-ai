package runner

import (
	"errors"
	"path/filepath"
	"reflect"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/tanq16/tiny-ai-suite/internal/catalog"
)

func TestBuildArgs(t *testing.T) {
	stems, err := catalog.Get("stems")
	if err != nil {
		t.Fatalf("catalog.Get(stems) = %v", err)
	}
	ocr, err := catalog.Get("ocr")
	if err != nil {
		t.Fatalf("catalog.Get(ocr) = %v", err)
	}
	transcribe, err := catalog.Get("transcribe")
	if err != nil {
		t.Fatalf("catalog.Get(transcribe) = %v", err)
	}

	tests := []struct {
		name   string
		task   catalog.Task
		values map[string]string
		files  map[string]string
		want   []string
	}{
		{
			name: "declared order regardless of map order",
			task: stems,
			values: map[string]string{
				"shifts": "2", "format": "mp3", "model": "htdemucs", "two-stems": "true",
			},
			files: map[string]string{"input": "/jobs/j1/input/song.mp3"},
			want: []string{
				"run", "--project", "/scripts/stems", "stems", "--json", "--outdir", "/jobs/j1/output",
				"--input", "/jobs/j1/input/song.mp3", "--model", "htdemucs", "--two-stems",
				"--format", "mp3", "--shifts", "2",
			},
		},
		{
			name:   "false bool is omitted entirely",
			task:   stems,
			values: map[string]string{"two-stems": "false", "model": "mdx_extra"},
			files:  map[string]string{"input": "/in.wav"},
			want: []string{
				"run", "--project", "/scripts/stems", "stems", "--json", "--outdir", "/jobs/j1/output",
				"--input", "/in.wav", "--model", "mdx_extra",
			},
		},
		{
			name:   "checkbox on is truthy",
			task:   stems,
			values: map[string]string{"two-stems": "on"},
			files:  map[string]string{"input": "/in.wav"},
			want: []string{
				"run", "--project", "/scripts/stems", "stems", "--json", "--outdir", "/jobs/j1/output",
				"--input", "/in.wav", "--two-stems",
			},
		},
		{
			name:   "a bool defaulting on is switched off with the negated flag",
			task:   ocr,
			values: map[string]string{"tables": "false", "annotate": "true"},
			files:  map[string]string{"input": "/receipt.png"},
			want: []string{
				"run", "--project", "/scripts/ocr", "ocr", "--json", "--outdir", "/jobs/j1/output",
				"--input", "/receipt.png", "--no-tables", "--annotate",
			},
		},
		{
			name:  "an unsubmitted bool defaulting on is negated too, since a browser omits an unchecked box",
			task:  ocr,
			files: map[string]string{"input": "/receipt.png"},
			want: []string{
				"run", "--project", "/scripts/ocr", "ocr", "--json", "--outdir", "/jobs/j1/output",
				"--input", "/receipt.png", "--no-tables", "--no-annotate",
			},
		},
		{
			name:   "empty text values are dropped",
			task:   transcribe,
			values: map[string]string{"language": "", "task": "translate"},
			files:  map[string]string{"input": "/clip.m4a"},
			want: []string{
				"run", "--project", "/scripts/transcribe", "transcribe", "--json", "--outdir", "/jobs/j1/output",
				"--input", "/clip.m4a", "--task", "translate",
			},
		},
		{
			name:   "missing file param contributes no flag",
			task:   stems,
			values: map[string]string{"model": "htdemucs"},
			files:  nil,
			want: []string{
				"run", "--project", "/scripts/stems", "stems", "--json", "--outdir", "/jobs/j1/output",
				"--model", "htdemucs",
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := buildArgs(tt.task, "/scripts/"+tt.task.Project, "/jobs/j1/output", tt.values, tt.files)
			if !slices.Equal(got, tt.want) {
				t.Errorf("buildArgs() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestParseLine(t *testing.T) {
	f := func(v float64) *float64 { return &v }
	tests := []struct {
		name string
		line string
		want Event
		keep bool
	}{
		{"blank line is skipped", "   ", Event{}, false},
		{
			name: "progress carries its fields",
			line: `{"event":"progress","fraction":0.42,"message":"separating","current":42,"total":100}`,
			want: Event{Event: EventProgress, Fraction: f(0.42), Message: "separating", Current: new(42), Total: new(100)},
			keep: true,
		},
		{
			name: "null fraction stays absent",
			line: `{"event":"progress","fraction":null,"message":"loading","current":null,"total":null}`,
			want: Event{Event: EventProgress, Message: "loading"},
			keep: true,
		},
		{
			name: "malformed json becomes a log line",
			line: `Loading model weights...`,
			want: Event{Event: EventLog, Level: "info", Message: "Loading model weights..."},
			keep: true,
		},
		{
			name: "truncated json becomes a log line",
			line: `{"event":"progress","fraction":0.4`,
			want: Event{Event: EventLog, Level: "info", Message: `{"event":"progress","fraction":0.4`},
			keep: true,
		},
		{
			name: "json that is not an object becomes a log line",
			line: `[1,2,3]`,
			want: Event{Event: EventLog, Level: "info", Message: "[1,2,3]"},
			keep: true,
		},
		{
			name: "unknown event name becomes a log line",
			line: `{"event":"telemetry","message":"hi"}`,
			want: Event{Event: EventLog, Level: "info", Message: `{"event":"telemetry","message":"hi"}`},
			keep: true,
		},
		{
			name: "a script cannot forge seq or state",
			line: `{"event":"log","level":"warn","message":"careful","seq":999,"state":"succeeded"}`,
			want: Event{Event: EventLog, Level: "warn", Message: "careful"},
			keep: true,
		},
		{
			name: "artifact keeps its path and size",
			line: `{"event":"artifact","path":"/out/vocals.wav","kind":"audio","label":"Vocals","bytes":1234}`,
			want: Event{Event: EventArtifact, Path: "/out/vocals.wav", Kind: "audio", Label: "Vocals", Bytes: new(int64(1234))},
			keep: true,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, ok := parseLine(tt.line)
			if ok != tt.keep {
				t.Fatalf("parseLine(%q) kept = %v, want %v", tt.line, ok, tt.keep)
			}
			if ok && !reflect.DeepEqual(got, tt.want) {
				t.Errorf("parseLine(%q) = %+v, want %+v", tt.line, got, tt.want)
			}
		})
	}
}

func TestValidate(t *testing.T) {
	stems, _ := catalog.Get("stems")
	tts, _ := catalog.Get("tts")

	tests := []struct {
		name    string
		task    catalog.Task
		values  map[string]string
		files   map[string]string
		wantErr string
	}{
		{"complete submission", stems, map[string]string{"model": "htdemucs"}, map[string]string{"input": "/a.wav"}, ""},
		{"unknown parameter", stems, map[string]string{"nope": "1"}, map[string]string{"input": "/a.wav"}, `task "stems" has no parameter "nope"`},
		{"missing required file", stems, map[string]string{"model": "htdemucs"}, nil, `parameter "input" is required`},
		{"missing required text", tts, map[string]string{"voice": "af_heart"}, nil, `parameter "text" is required`},
		{"whitespace does not satisfy required text", tts, map[string]string{"text": "   "}, nil, `parameter "text" is required`},
		{"file param sent as text", stems, map[string]string{"input": "/a.wav"}, nil, `parameter "input" must be sent as a file`},
		{"text param sent as a file", tts, map[string]string{"text": "hi"}, map[string]string{"voice": "/a.wav"}, `parameter "voice" is not a file`},
		{"unknown file parameter", stems, nil, map[string]string{"input": "/a.wav", "extra": "/b.wav"}, `task "stems" has no parameter "extra"`},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := validate(tt.task, tt.values, tt.files)
			if tt.wantErr == "" {
				if err != nil {
					t.Fatalf("validate() = %v, want nil", err)
				}
				return
			}
			var invalid *ValidationError
			if !errors.As(err, &invalid) {
				t.Fatalf("validate() = %v, want a *ValidationError", err)
			}
			if invalid.Error() != tt.wantErr {
				t.Errorf("validate() = %q, want %q", invalid.Error(), tt.wantErr)
			}
		})
	}
}

func TestSanitizeFilename(t *testing.T) {
	tests := []struct{ in, want string }{
		{"song.mp3", "song.mp3"},
		{"../../etc/passwd", "passwd"},
		{"/abs/path/clip.wav", "clip.wav"},
		{`..\..\windows\system32`, ".._.._windows_system32"},
		{"", "upload"},
		{"..", "upload"},
		{".", "upload"},
		{"bad\x00name.wav", "bad_name.wav"},
	}
	for _, tt := range tests {
		t.Run(tt.in, func(t *testing.T) {
			if got := sanitizeFilename(tt.in); got != tt.want {
				t.Errorf("sanitizeFilename(%q) = %q, want %q", tt.in, got, tt.want)
			}
		})
	}
}

func TestArtifactPathGuard(t *testing.T) {
	r := newTestRunner(t)
	job := submitTTS(t, r)
	outDir := filepath.Join(r.jobsDir, job.ID, "output")

	tests := []struct {
		name    string
		in      string
		want    string
		wantErr error
	}{
		{"plain name", "vocals.wav", filepath.Join(outDir, "vocals.wav"), nil},
		{"nested name", "pages/1.png", filepath.Join(outDir, "pages", "1.png"), nil},
		{"parent escape", "../input/song.mp3", "", ErrNoArtifact},
		{"deep escape", "../../../etc/passwd", "", ErrNoArtifact},
		{"bare parent", "..", "", ErrNoArtifact},
		{"absolute name is confined", "/etc/passwd", filepath.Join(outDir, "etc", "passwd"), nil},
		{"empty name", "", "", ErrNoArtifact},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, err := r.ArtifactPath(job.ID, tt.in)
			if !errors.Is(err, tt.wantErr) {
				t.Fatalf("ArtifactPath(%q) err = %v, want %v", tt.in, err, tt.wantErr)
			}
			if got != tt.want {
				t.Errorf("ArtifactPath(%q) = %q, want %q", tt.in, got, tt.want)
			}
		})
	}

	if _, err := r.ArtifactPath("no-such-job", "x.wav"); !errors.Is(err, ErrJobNotFound) {
		t.Errorf("ArtifactPath on an unknown job = %v, want ErrJobNotFound", err)
	}
}

func TestStateTransitions(t *testing.T) {
	t.Run("running to succeeded pins timestamps and completes progress", func(t *testing.T) {
		rec := newRecord(t)
		rec.transition(StateRunning)
		rec.apply(Event{Event: EventProgress, Fraction: ptr(0.5), Message: "half"})
		rec.transition(StateSucceeded)

		snap := rec.snapshot(false)
		if snap.State != StateSucceeded {
			t.Fatalf("state = %q, want succeeded", snap.State)
		}
		if snap.StartedAt == nil || snap.FinishedAt == nil {
			t.Fatalf("startedAt = %v, finishedAt = %v, want both set", snap.StartedAt, snap.FinishedAt)
		}
		if snap.Progress.Fraction != 1 {
			t.Errorf("progress fraction = %v, want 1", snap.Progress.Fraction)
		}
	})

	t.Run("a terminal job never transitions again", func(t *testing.T) {
		rec := newRecord(t)
		rec.transition(StateRunning)
		rec.transition(StateFailed)
		rec.transition(StateSucceeded)
		if got := rec.snapshot(false).State; got != StateFailed {
			t.Errorf("state = %q, want failed", got)
		}
	})

	t.Run("queued cancels without ever starting", func(t *testing.T) {
		rec := newRecord(t)
		rec.transition(StateCanceled)
		snap := rec.snapshot(false)
		if snap.State != StateCanceled {
			t.Fatalf("state = %q, want canceled", snap.State)
		}
		if snap.StartedAt != nil {
			t.Errorf("startedAt = %v, want nil", snap.StartedAt)
		}
	})

	t.Run("an error event keeps the first message and fails the job", func(t *testing.T) {
		rec := newRecord(t)
		rec.transition(StateRunning)
		rec.apply(Event{Event: EventError, Message: "CUDA out of memory"})
		rec.apply(Event{Event: EventError, Message: "secondary noise"})
		rec.finish(nil, false)
		snap := rec.snapshot(false)
		if snap.State != StateFailed {
			t.Fatalf("state = %q, want failed", snap.State)
		}
		if snap.Error != "CUDA out of memory" {
			t.Errorf("error = %q, want the first reported message", snap.Error)
		}
	})

	t.Run("cancellation outranks a non-zero exit", func(t *testing.T) {
		rec := newRecord(t)
		rec.transition(StateRunning)
		rec.canceled = true
		rec.finish(errors.New("signal: killed"), false)
		if got := rec.snapshot(false).State; got != StateCanceled {
			t.Errorf("state = %q, want canceled", got)
		}
	})

	t.Run("a runner-wide stop cancels rather than fails", func(t *testing.T) {
		rec := newRecord(t)
		rec.transition(StateRunning)
		rec.finish(errors.New("signal: killed"), true)
		snap := rec.snapshot(false)
		if snap.State != StateCanceled {
			t.Errorf("state = %q, want canceled", snap.State)
		}
		if snap.Error != "" {
			t.Errorf("error = %q, want empty", snap.Error)
		}
	})

	t.Run("every transition emits a state event", func(t *testing.T) {
		rec := newRecord(t)
		rec.publish(Event{Event: EventState, State: StateQueued})
		rec.transition(StateRunning)
		rec.transition(StateSucceeded)

		var states []State
		for _, e := range rec.snapshot(true).Events {
			if e.Event == EventState {
				states = append(states, e.State)
			}
		}
		want := []State{StateQueued, StateRunning, StateSucceeded}
		if !slices.Equal(states, want) {
			t.Errorf("state events = %v, want %v", states, want)
		}
	})
}

func TestSubscribeReplay(t *testing.T) {
	rec := newRecord(t)
	for i := range 5 {
		rec.publish(Event{Event: EventLog, Message: string(rune('a' + i))})
	}

	tests := []struct {
		name string
		from int
		want []int
	}{
		{"from zero replays everything", 0, []int{1, 2, 3, 4, 5}},
		{"from one replays everything", 1, []int{1, 2, 3, 4, 5}},
		{"from is inclusive", 3, []int{3, 4, 5}},
		{"from the last event", 5, []int{5}},
		{"past the end replays nothing", 6, nil},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			sub := rec.subscribe(tt.from)
			defer sub.Close()
			var seqs []int
			for _, e := range sub.Backlog {
				seqs = append(seqs, e.Seq)
			}
			if !slices.Equal(seqs, tt.want) {
				t.Errorf("backlog seqs = %v, want %v", seqs, tt.want)
			}
		})
	}

	t.Run("a live subscriber receives what follows the replay", func(t *testing.T) {
		sub := rec.subscribe(5)
		defer sub.Close()
		if len(sub.Backlog) != 1 || sub.Backlog[0].Seq != 5 {
			t.Fatalf("backlog = %v, want just seq 5", sub.Backlog)
		}
		rec.publish(Event{Event: EventLog, Message: "f"})
		select {
		case e := <-sub.Events:
			if e.Seq != 6 {
				t.Errorf("live event seq = %d, want 6", e.Seq)
			}
		case <-time.After(time.Second):
			t.Fatal("timed out waiting for the live event")
		}
	})

	t.Run("a terminal job hands back no live channel", func(t *testing.T) {
		rec.transition(StateSucceeded)
		sub := rec.subscribe(0)
		defer sub.Close()
		if sub.Events != nil {
			t.Error("Events channel is non-nil for a finished job")
		}
		if len(sub.Backlog) == 0 {
			t.Error("backlog is empty for a finished job")
		}
	})

	t.Run("terminating closes live subscribers", func(t *testing.T) {
		other := newRecord(t)
		other.transition(StateRunning)
		sub := other.subscribe(0)
		defer sub.Close()
		other.transition(StateFailed)
		for {
			select {
			case _, ok := <-sub.Events:
				if !ok {
					return
				}
			case <-time.After(time.Second):
				t.Fatal("subscriber channel was never closed")
			}
		}
	})
}

func TestSlowSubscriberIsDropped(t *testing.T) {
	rec := newRecord(t)
	sub := rec.subscribe(0)
	defer sub.Close()

	for range subscriberBuffer + 10 {
		rec.publish(Event{Event: EventLog, Message: "flood"})
	}
	drained := 0
	for range sub.Events {
		drained++
	}
	if drained != subscriberBuffer {
		t.Errorf("drained %d events before the channel closed, want %d", drained, subscriberBuffer)
	}
	if got := len(rec.snapshot(true).Events); got != subscriberBuffer+10 {
		t.Errorf("history holds %d events, want %d", got, subscriberBuffer+10)
	}
}

func TestArtifactName(t *testing.T) {
	tests := []struct{ name, outDir, reported, want string }{
		{"inside the output directory", "/jobs/j1/output", "/jobs/j1/output/vocals.wav", "vocals.wav"},
		{"nested inside", "/jobs/j1/output", "/jobs/j1/output/htdemucs/song/bass.wav", "htdemucs/song/bass.wav"},
		{"outside falls back to the base name", "/jobs/j1/output", "/tmp/elsewhere.wav", "elsewhere.wav"},
		{"empty stays empty", "/jobs/j1/output", "", ""},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := artifactName(tt.outDir, tt.reported); got != tt.want {
				t.Errorf("artifactName(%q, %q) = %q, want %q", tt.outDir, tt.reported, got, tt.want)
			}
		})
	}
}

func TestReloadFailsInterruptedJobs(t *testing.T) {
	dataDir := t.TempDir()
	r := newRunnerAt(t, dataDir)
	job := submitTTS(t, r)

	if got := job.State; got != StateQueued {
		t.Fatalf("fresh job state = %q, want queued", got)
	}

	reloaded := newRunnerAt(t, dataDir)
	got, err := reloaded.Get(job.ID, true)
	if err != nil {
		t.Fatalf("Get after reload = %v", err)
	}
	if got.State != StateFailed {
		t.Fatalf("state after reload = %q, want failed", got.State)
	}
	if !strings.Contains(got.Error, "interrupted") {
		t.Errorf("error after reload = %q, want it to name the interruption", got.Error)
	}
	if len(got.Events) == 0 || got.Events[len(got.Events)-1].State != StateFailed {
		t.Errorf("last event = %+v, want a failed state event", got.Events[len(got.Events)-1:])
	}
}

func ptr(v float64) *float64 { return &v }

func newRecord(t *testing.T) *record {
	t.Helper()
	dir := t.TempDir()
	return &record{
		snap:   Job{ID: "test-job", State: StateQueued, Artifacts: []Artifact{}},
		subs:   make(map[chan Event]struct{}),
		done:   make(chan struct{}),
		dir:    dir,
		outDir: filepath.Join(dir, "output"),
	}
}

func newTestRunner(t *testing.T) *Runner {
	t.Helper()
	return newRunnerAt(t, t.TempDir())
}

func newRunnerAt(t *testing.T, dataDir string) *Runner {
	t.Helper()
	r, err := New(Config{DataDir: dataDir, ScriptsDir: t.TempDir(), Workers: 1})
	if err != nil {
		t.Fatalf("New() = %v", err)
	}
	t.Cleanup(r.Stop)
	return r
}

func submitTTS(t *testing.T, r *Runner) Job {
	t.Helper()
	job, err := r.Submit(Submission{TaskID: "tts", Values: map[string]string{"text": "hello"}})
	if err != nil {
		t.Fatalf("Submit() = %v", err)
	}
	return job
}
