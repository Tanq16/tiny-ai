package server

import (
	"context"
	"embed"
	"errors"
	"fmt"
	"io/fs"
	"net"
	"net/http"
	"time"

	"github.com/Tanq16/tiny-ai/internal/runner"
	"github.com/rs/zerolog/log"
)

//go:embed all:static
var staticFiles embed.FS

const shutdownGrace = 5 * time.Second

type Server struct {
	host    string
	port    int
	dataDir string
	mux     *http.ServeMux
	runner  *runner.Runner
}

func New(host string, port int, dataDir string, r *runner.Runner) *Server {
	return &Server{host: host, port: port, dataDir: dataDir, mux: http.NewServeMux(), runner: r}
}

func (s *Server) Setup() error {
	staticFS, err := fs.Sub(staticFiles, "static")
	if err != nil {
		return err
	}
	s.mux.Handle("GET /static/", http.StripPrefix("/static/", http.FileServer(http.FS(staticFS))))

	s.mux.HandleFunc("GET /api/health", s.handleHealth)
	s.mux.HandleFunc("GET /api/tasks", s.handleTasks)
	s.mux.HandleFunc("GET /api/lexicon", s.handleGetLexicon)
	s.mux.HandleFunc("PUT /api/lexicon", s.handlePutLexicon)
	s.mux.HandleFunc("GET /api/jobs", s.handleListJobs)
	s.mux.HandleFunc("POST /api/jobs", s.handleCreateJob)
	s.mux.HandleFunc("GET /api/jobs/{id}", s.handleGetJob)
	s.mux.HandleFunc("DELETE /api/jobs/{id}", s.handleDeleteJob)
	s.mux.HandleFunc("GET /api/jobs/{id}/events", s.handleJobEvents)
	s.mux.HandleFunc("POST /api/jobs/{id}/cancel", s.handleCancelJob)
	s.mux.HandleFunc("POST /api/jobs/{id}/messages", s.handleSendMessage)
	s.mux.HandleFunc("POST /api/jobs/{id}/finish", s.handleFinishChat)
	s.mux.HandleFunc("GET /api/jobs/{id}/artifacts/{name...}", s.handleArtifact)
	s.mux.HandleFunc("GET /api/jobs/{id}/inputs/{name...}", s.handleInput)
	s.mux.HandleFunc("/api/", s.handleAPINotFound)

	s.mux.HandleFunc("/", s.handleIndex)
	return nil
}

func (s *Server) Run(ctx context.Context) error {
	baseCtx, cancelBase := context.WithCancel(ctx)
	defer cancelBase()

	addr := fmt.Sprintf("%s:%d", s.host, s.port)
	srv := &http.Server{
		Addr:        addr,
		Handler:     s.mux,
		BaseContext: func(net.Listener) context.Context { return baseCtx },
	}

	errCh := make(chan error, 1)
	go func() { errCh <- srv.ListenAndServe() }()
	log.Info().Str("url", "http://"+addr).Msg("listening")

	select {
	case err := <-errCh:
		if errors.Is(err, http.ErrServerClosed) {
			return nil
		}
		return err
	case <-ctx.Done():
		log.Info().Msg("shutting down")
		cancelBase()
		shutdownCtx, cancel := context.WithTimeout(context.Background(), shutdownGrace)
		defer cancel()
		return srv.Shutdown(shutdownCtx)
	}
}

func (s *Server) handleIndex(w http.ResponseWriter, r *http.Request) {
	data, err := staticFiles.ReadFile("static/index.html")
	if err != nil {
		http.Error(w, "Not found", http.StatusNotFound)
		return
	}
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.Write(data)
}
