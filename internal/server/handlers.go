package server

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"maps"
	"mime"
	"net/http"
	"os"
	"path"
	"slices"
	"strconv"

	"github.com/Tanq16/tiny-ai/internal/catalog"
	"github.com/Tanq16/tiny-ai/internal/lexicon"
	"github.com/Tanq16/tiny-ai/internal/runner"
	"github.com/rs/zerolog/log"
)

const (
	maxFormMemory   = 32 << 20
	maxLexiconBytes = 1 << 20
)

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(v); err != nil {
		log.Error().Err(err).Msg("failed to write response")
	}
}

func writeError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"error": msg})
}

func (s *Server) handleHealth(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

func (s *Server) handleAPINotFound(w http.ResponseWriter, r *http.Request) {
	writeError(w, http.StatusNotFound, "unknown endpoint")
}

func (s *Server) handleTasks(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{
		"groups": catalog.Groups(),
		"tasks":  catalog.All(),
	})
}

func (s *Server) handleListJobs(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{"jobs": s.runner.List()})
}

func (s *Server) handleCreateJob(w http.ResponseWriter, r *http.Request) {
	if err := r.ParseMultipartForm(maxFormMemory); err != nil {
		writeError(w, http.StatusBadRequest, "expected a multipart/form-data submission")
		return
	}
	defer r.MultipartForm.RemoveAll()

	values := make(map[string]string, len(r.MultipartForm.Value))
	for name, vals := range r.MultipartForm.Value {
		if name == "task" || len(vals) == 0 {
			continue
		}
		values[name] = vals[0]
	}
	taskID := r.FormValue("task")
	if taskID == "" {
		writeError(w, http.StatusBadRequest, "field \"task\" is required")
		return
	}

	uploads := make([]runner.Upload, 0, len(r.MultipartForm.File))
	var closers []io.Closer
	defer func() {
		for _, c := range closers {
			c.Close()
		}
	}()
	for name, headers := range r.MultipartForm.File {
		if len(headers) == 0 {
			continue
		}
		f, err := headers[0].Open()
		if err != nil {
			log.Error().Err(err).Str("field", name).Msg("failed to read upload")
			writeError(w, http.StatusBadRequest, fmt.Sprintf("could not read the upload for %q", name))
			return
		}
		closers = append(closers, f)
		uploads = append(uploads, runner.Upload{Param: name, Filename: headers[0].Filename, Content: f})
	}

	job, err := s.runner.Submit(runner.Submission{TaskID: taskID, Values: values, Files: uploads})
	switch {
	case errors.Is(err, runner.ErrUnknownTask):
		writeError(w, http.StatusNotFound, err.Error())
	case errors.Is(err, runner.ErrQueueFull):
		writeError(w, http.StatusServiceUnavailable, err.Error())
	case errors.Is(err, runner.ErrChatBusy):
		writeError(w, http.StatusConflict, "finish the open chat before starting another")
	case err != nil:
		if invalid, ok := errors.AsType[*runner.ValidationError](err); ok {
			writeError(w, http.StatusBadRequest, invalid.Error())
			return
		}
		log.Error().Err(err).Str("task", taskID).Msg("failed to queue job")
		writeError(w, http.StatusInternalServerError, "could not queue the job")
	default:
		log.Info().Str("job", job.ID).Str("task", job.Task).Msg("queued job")
		writeJSON(w, http.StatusCreated, job)
	}
}

func (s *Server) handleGetJob(w http.ResponseWriter, r *http.Request) {
	job, err := s.runner.Get(r.PathValue("id"), true)
	if err != nil {
		writeError(w, http.StatusNotFound, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, job)
}

func (s *Server) handleCancelJob(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	switch err := s.runner.Cancel(id); {
	case errors.Is(err, runner.ErrJobNotFound):
		writeError(w, http.StatusNotFound, err.Error())
	case errors.Is(err, runner.ErrJobFinished):
		writeError(w, http.StatusConflict, err.Error())
	case err != nil:
		log.Error().Err(err).Str("job", id).Msg("failed to cancel job")
		writeError(w, http.StatusInternalServerError, "could not cancel the job")
	default:
		log.Info().Str("job", id).Msg("canceled job")
		writeJSON(w, http.StatusAccepted, map[string]string{"status": "canceling"})
	}
}

func (s *Server) handleDeleteJob(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	switch err := s.runner.Delete(id); {
	case errors.Is(err, runner.ErrJobNotFound):
		writeError(w, http.StatusNotFound, err.Error())
	case err != nil:
		log.Error().Err(err).Str("job", id).Msg("failed to delete job")
		writeError(w, http.StatusInternalServerError, "could not delete the job")
	default:
		w.WriteHeader(http.StatusNoContent)
	}
}

func (s *Server) handleArtifact(w http.ResponseWriter, r *http.Request) {
	name := r.PathValue("name")
	full, err := s.runner.ArtifactPath(r.PathValue("id"), name)
	serveFile(w, r, full, name, err)
}

func (s *Server) handleInput(w http.ResponseWriter, r *http.Request) {
	name := r.PathValue("name")
	full, err := s.runner.InputPath(r.PathValue("id"), name)
	serveFile(w, r, full, name, err)
}

func serveFile(w http.ResponseWriter, r *http.Request, full, name string, err error) {
	if err != nil {
		writeError(w, http.StatusNotFound, err.Error())
		return
	}
	info, err := os.Stat(full)
	if err != nil || info.IsDir() {
		writeError(w, http.StatusNotFound, runner.ErrNoArtifact.Error())
		return
	}
	disposition := "attachment"
	if r.URL.Query().Get("inline") == "1" {
		disposition = "inline"
	}
	w.Header().Set("Content-Disposition", mime.FormatMediaType(disposition, map[string]string{"filename": path.Base(name)}))
	http.ServeFile(w, r, full)
}

func (s *Server) handleSendMessage(w http.ResponseWriter, r *http.Request) {
	if err := r.ParseMultipartForm(maxFormMemory); err != nil {
		writeError(w, http.StatusBadRequest, "expected a multipart/form-data submission")
		return
	}
	defer r.MultipartForm.RemoveAll()

	msg := runner.Message{Text: r.FormValue("text")}
	var closers []io.Closer
	defer func() {
		for _, c := range closers {
			c.Close()
		}
	}()
	for _, field := range slices.Sorted(maps.Keys(r.MultipartForm.File)) {
		for _, header := range r.MultipartForm.File[field] {
			f, err := header.Open()
			if err != nil {
				log.Error().Err(err).Str("filename", header.Filename).Msg("failed to read chat attachment")
				writeError(w, http.StatusBadRequest, fmt.Sprintf("could not read the attachment %q", header.Filename))
				return
			}
			closers = append(closers, f)
			msg.Files = append(msg.Files, runner.Upload{Filename: header.Filename, Content: f})
		}
	}

	id := r.PathValue("id")
	job, err := s.runner.Send(id, msg)
	if err != nil {
		writeChatError(w, id, "send to", err)
		return
	}
	writeJSON(w, http.StatusAccepted, job)
}

func (s *Server) handleFinishChat(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	if err := s.runner.Finish(id); err != nil {
		writeChatError(w, id, "finish", err)
		return
	}
	log.Info().Str("job", id).Msg("finished chat")
	writeJSON(w, http.StatusAccepted, map[string]string{"status": "finishing"})
}

func writeChatError(w http.ResponseWriter, id, action string, err error) {
	switch {
	case errors.Is(err, runner.ErrJobNotFound):
		writeError(w, http.StatusNotFound, err.Error())
	case errors.Is(err, runner.ErrNotInteractive):
		writeError(w, http.StatusBadRequest, err.Error())
	case errors.Is(err, runner.ErrJobFinished), errors.Is(err, runner.ErrChatNotReady):
		writeError(w, http.StatusConflict, err.Error())
	default:
		if invalid, ok := errors.AsType[*runner.ValidationError](err); ok {
			writeError(w, http.StatusBadRequest, invalid.Error())
			return
		}
		log.Error().Err(err).Str("job", id).Str("action", action).Msg("failed chat action")
		writeError(w, http.StatusInternalServerError, "could not "+action+" the chat")
	}
}

func (s *Server) handleJobEvents(w http.ResponseWriter, r *http.Request) {
	from := 0
	if v := r.URL.Query().Get("from"); v != "" {
		parsed, err := strconv.Atoi(v)
		if err != nil {
			writeError(w, http.StatusBadRequest, "query parameter \"from\" must be a number")
			return
		}
		from = parsed
	}
	sub, err := s.runner.Subscribe(r.PathValue("id"), from)
	if err != nil {
		writeError(w, http.StatusNotFound, err.Error())
		return
	}
	defer sub.Close()

	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	w.Header().Set("X-Accel-Buffering", "no")
	w.WriteHeader(http.StatusOK)

	flusher := http.NewResponseController(w)
	for _, e := range sub.Backlog {
		if err := writeSSE(w, e); err != nil {
			return
		}
	}
	flusher.Flush()
	if sub.Events == nil {
		return
	}

	for {
		select {
		case <-r.Context().Done():
			return
		case e, ok := <-sub.Events:
			if !ok {
				return
			}
			if err := writeSSE(w, e); err != nil {
				return
			}
			flusher.Flush()
		}
	}
}

func writeSSE(w io.Writer, e runner.Event) error {
	payload, err := json.Marshal(e)
	if err != nil {
		return err
	}
	_, err = fmt.Fprintf(w, "id: %d\ndata: %s\n\n", e.Seq, payload)
	return err
}

func (s *Server) handleGetLexicon(w http.ResponseWriter, r *http.Request) {
	lex, err := lexicon.Load(lexicon.Path(s.dataDir))
	if err != nil {
		log.Error().Err(err).Msg("failed to read the lexicon")
		writeError(w, http.StatusInternalServerError, "could not read the lexicon")
		return
	}
	writeJSON(w, http.StatusOK, lex)
}

func (s *Server) handlePutLexicon(w http.ResponseWriter, r *http.Request) {
	var lex lexicon.Lexicon
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, maxLexiconBytes)).Decode(&lex); err != nil {
		writeError(w, http.StatusBadRequest, "expected a lexicon object")
		return
	}
	lex = lex.Normalize()
	if err := lexicon.Save(lexicon.Path(s.dataDir), lex); err != nil {
		log.Error().Err(err).Msg("failed to write the lexicon")
		writeError(w, http.StatusInternalServerError, "could not save the lexicon")
		return
	}
	writeJSON(w, http.StatusOK, lex)
}
