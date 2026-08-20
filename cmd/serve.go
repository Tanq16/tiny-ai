package cmd

import (
	"log"
	"os"
	"os/signal"
	"syscall"

	"github.com/Tanq16/tiny-ai/internal/runner"
	"github.com/Tanq16/tiny-ai/internal/server"
	"github.com/spf13/cobra"
)

var serveFlags struct {
	host    string
	port    int
	data    string
	scripts string
	jobs    int
}

var serveCmd = &cobra.Command{
	Use:   "serve",
	Short: "Start the web server",
	Run: func(cmd *cobra.Command, args []string) {
		if serveFlags.jobs < 1 {
			log.Fatalf("ERROR --jobs must be at least 1")
		}

		ctx, stop := signal.NotifyContext(cmd.Context(), os.Interrupt, syscall.SIGTERM)
		defer stop()

		jobs, err := runner.New(runner.Config{
			DataDir:    serveFlags.data,
			ScriptsDir: serveFlags.scripts,
			Workers:    serveFlags.jobs,
		})
		if err != nil {
			log.Fatalf("ERROR Failed to prepare the job runner: %v", err)
		}
		jobs.Start()
		log.Printf("INFO Running %d job(s) at a time from %s", serveFlags.jobs, serveFlags.scripts)

		srv := server.New(serveFlags.host, serveFlags.port, serveFlags.data, jobs)
		if err := srv.Setup(); err != nil {
			log.Fatalf("ERROR Failed to set up the server: %v", err)
		}
		if err := srv.Run(ctx); err != nil {
			jobs.Stop()
			log.Fatalf("ERROR Server error: %v", err)
		}
		jobs.Stop()
	},
}

func init() {
	serveCmd.Flags().StringVarP(&serveFlags.host, "host", "H", "127.0.0.1", "Host to bind to")
	serveCmd.Flags().IntVarP(&serveFlags.port, "port", "p", 7777, "Port to listen on")
	serveCmd.Flags().StringVarP(&serveFlags.data, "data", "d", "./data", "Directory holding job inputs, outputs and history")
	serveCmd.Flags().StringVarP(&serveFlags.scripts, "scripts", "s", "./ai-scripts", "Directory holding the task projects")
	serveCmd.Flags().IntVarP(&serveFlags.jobs, "jobs", "j", 1, "Jobs to run at the same time")
}
