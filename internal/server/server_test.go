package server

import (
	"bytes"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/Tanq16/tiny-ai/internal/runner"
)

func TestWriteSSE(t *testing.T) {
	at := time.Date(2026, 8, 19, 15, 30, 14, 0, time.UTC)
	fraction := 0.42

	var buf bytes.Buffer
	e := runner.Event{Seq: 7, At: at, Event: runner.EventProgress, Fraction: &fraction, Message: "separating"}
	if err := writeSSE(&buf, e); err != nil {
		t.Fatalf("writeSSE() = %v", err)
	}
	want := "id: 7\ndata: {\"seq\":7,\"at\":\"2026-08-19T15:30:14Z\",\"event\":\"progress\",\"fraction\":0.42,\"message\":\"separating\"}\n\n"
	if buf.String() != want {
		t.Errorf("frame =\n%q\nwant\n%q", buf.String(), want)
	}
}

func TestWriteSSEEscapesNewlines(t *testing.T) {
	var buf bytes.Buffer
	e := runner.Event{Seq: 1, Event: runner.EventLog, Level: "warn", Message: "line one\nline two"}
	if err := writeSSE(&buf, e); err != nil {
		t.Fatalf("writeSSE() = %v", err)
	}
	if got := strings.Count(buf.String(), "\n"); got != 3 {
		t.Errorf("frame carries %d newlines, want 3 (id, data, terminator)", got)
	}
}

func TestArtifactHandler(t *testing.T) {
	srv, job := newTestServer(t)

	full, err := srv.runner.ArtifactPath(job.ID, "vocals.wav")
	if err != nil {
		t.Fatalf("ArtifactPath() = %v", err)
	}
	if err := os.WriteFile(full, []byte("riff"), 0o600); err != nil {
		t.Fatalf("seeding the artifact = %v", err)
	}

	tests := []struct {
		name       string
		target     string
		wantStatus int
		wantDisp   string
	}{
		{"download by default", "/api/jobs/" + job.ID + "/artifacts/vocals.wav", http.StatusOK, "attachment; filename=vocals.wav"},
		{"inline on request", "/api/jobs/" + job.ID + "/artifacts/vocals.wav?inline=1", http.StatusOK, "inline; filename=vocals.wav"},
		{"missing file", "/api/jobs/" + job.ID + "/artifacts/nope.wav", http.StatusNotFound, ""},
		{"encoded traversal is refused", "/api/jobs/" + job.ID + "/artifacts/%2e%2e%2f%2e%2e%2finput%2fsong.mp3", http.StatusNotFound, ""},
		{"plain traversal never reaches the handler", "/api/jobs/" + job.ID + "/artifacts/../../etc/passwd", http.StatusTemporaryRedirect, ""},
		{"unknown job", "/api/jobs/nope/artifacts/vocals.wav", http.StatusNotFound, ""},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			rec := httptest.NewRecorder()
			srv.mux.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, tt.target, nil))
			if rec.Code != tt.wantStatus {
				t.Fatalf("GET %s = %d, want %d", tt.target, rec.Code, tt.wantStatus)
			}
			if got := rec.Header().Get("Content-Disposition"); got != tt.wantDisp {
				t.Errorf("Content-Disposition = %q, want %q", got, tt.wantDisp)
			}
		})
	}
}

func TestCreateJobValidation(t *testing.T) {
	srv, _ := newTestServer(t)

	tests := []struct {
		name       string
		fields     map[string]string
		wantStatus int
	}{
		{"valid submission", map[string]string{"task": "tts", "text": "hello"}, http.StatusCreated},
		{"unknown task", map[string]string{"task": "nope", "text": "hello"}, http.StatusNotFound},
		{"unknown parameter", map[string]string{"task": "tts", "text": "hello", "bogus": "1"}, http.StatusBadRequest},
		{"missing required parameter", map[string]string{"task": "tts"}, http.StatusBadRequest},
		{"missing task field", map[string]string{"text": "hello"}, http.StatusBadRequest},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			body := &bytes.Buffer{}
			mw := multipart.NewWriter(body)
			for k, v := range tt.fields {
				if err := mw.WriteField(k, v); err != nil {
					t.Fatalf("WriteField(%q) = %v", k, err)
				}
			}
			mw.Close()

			req := httptest.NewRequest(http.MethodPost, "/api/jobs", body)
			req.Header.Set("Content-Type", mw.FormDataContentType())
			rec := httptest.NewRecorder()
			srv.mux.ServeHTTP(rec, req)
			if rec.Code != tt.wantStatus {
				t.Errorf("POST /api/jobs = %d (%s), want %d", rec.Code, rec.Body.String(), tt.wantStatus)
			}
		})
	}
}

func TestLexiconHandlers(t *testing.T) {
	srv, _ := newTestServer(t)

	rec := httptest.NewRecorder()
	srv.mux.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/api/lexicon", nil))
	if rec.Code != http.StatusOK {
		t.Fatalf("GET /api/lexicon = %d (%s), want 200", rec.Code, rec.Body.String())
	}
	if got := strings.TrimSpace(rec.Body.String()); got != `{"vocabulary":[],"corrections":[]}` {
		t.Errorf("GET on a fresh data directory = %s, want empty lists", got)
	}

	body := `{"vocabulary":[" MLX ","MLX",""],"corrections":[{"from":" tank sixteen ","to":"Tanq16"},{"from":"x","to":""}]}`
	rec = httptest.NewRecorder()
	put := httptest.NewRequest(http.MethodPut, "/api/lexicon", strings.NewReader(body))
	srv.mux.ServeHTTP(rec, put)
	if rec.Code != http.StatusOK {
		t.Fatalf("PUT /api/lexicon = %d (%s), want 200", rec.Code, rec.Body.String())
	}

	want := `{"vocabulary":["MLX"],"corrections":[{"from":"tank sixteen","to":"Tanq16"}]}`
	if got := strings.TrimSpace(rec.Body.String()); got != want {
		t.Errorf("PUT returned %s, want %s", got, want)
	}
	rec = httptest.NewRecorder()
	srv.mux.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/api/lexicon", nil))
	if got := strings.TrimSpace(rec.Body.String()); got != want {
		t.Errorf("GET after PUT = %s, want %s", got, want)
	}

	rec = httptest.NewRecorder()
	srv.mux.ServeHTTP(rec, httptest.NewRequest(http.MethodPut, "/api/lexicon", strings.NewReader("{not json")))
	if rec.Code != http.StatusBadRequest {
		t.Errorf("PUT with a malformed body = %d, want 400", rec.Code)
	}
}

func newTestServer(t *testing.T) (*Server, runner.Job) {
	t.Helper()
	dataDir := t.TempDir()
	jobs, err := runner.New(runner.Config{DataDir: dataDir, ScriptsDir: t.TempDir(), Workers: 1})
	if err != nil {
		t.Fatalf("runner.New() = %v", err)
	}
	t.Cleanup(jobs.Stop)

	srv := New("127.0.0.1", 0, dataDir, jobs)
	if err := srv.Setup(); err != nil {
		t.Fatalf("Setup() = %v", err)
	}
	job, err := jobs.Submit(runner.Submission{TaskID: "tts", Values: map[string]string{"text": "hello"}})
	if err != nil {
		t.Fatalf("Submit() = %v", err)
	}
	return srv, job
}
