package cmd

import (
	"errors"
	"os"
	"os/signal"
	"strconv"
	"syscall"

	"github.com/Tanq16/tiny-ai/internal/runner"
	"github.com/Tanq16/tiny-ai/internal/server"
	"github.com/rs/zerolog/log"
	"github.com/spf13/cobra"
)

type jobCount int

func (j *jobCount) String() string { return strconv.Itoa(int(*j)) }
func (j *jobCount) Type() string   { return "int>=1" }

func (j *jobCount) Set(v string) error {
	n, err := strconv.Atoi(v)
	if err != nil || n < 1 {
		return errors.New("must be a whole number of at least 1")
	}
	*j = jobCount(n)
	return nil
}

var serveFlags = struct {
	host    string
	port    int
	data    string
	scripts string
	jobs    jobCount
}{jobs: 1}

var serveCmd = &cobra.Command{
	Use:   "serve",
	Short: "Start the web server",
	Args:  cobra.NoArgs,
	Run: func(cmd *cobra.Command, args []string) {
		ctx, stop := signal.NotifyContext(cmd.Context(), os.Interrupt, syscall.SIGTERM)
		defer stop()

		jobs, err := runner.New(runner.Config{
			DataDir:    serveFlags.data,
			ScriptsDir: serveFlags.scripts,
			Workers:    int(serveFlags.jobs),
		})
		if err != nil {
			log.Fatal().Err(err).Msg("failed to prepare the job runner")
		}
		jobs.Start()
		log.Info().Int("jobs", int(serveFlags.jobs)).Str("scripts", serveFlags.scripts).Msg("running jobs")

		srv := server.New(serveFlags.host, serveFlags.port, serveFlags.data, jobs)
		if err := srv.Setup(); err != nil {
			log.Fatal().Err(err).Msg("failed to set up the server")
		}
		if err := srv.Run(ctx); err != nil {
			jobs.Stop()
			log.Fatal().Err(err).Msg("server error")
		}
		jobs.Stop()
	},
}

func init() {
	serveCmd.Flags().StringVarP(&serveFlags.host, "host", "H", "127.0.0.1", "Host to bind to")
	serveCmd.Flags().IntVarP(&serveFlags.port, "port", "p", 7777, "Port to listen on")
	serveCmd.Flags().StringVarP(&serveFlags.data, "data", "d", "./data", "Directory holding job inputs, outputs and history")
	serveCmd.Flags().StringVarP(&serveFlags.scripts, "scripts", "s", "./ai-scripts", "Directory holding the task projects")
	serveCmd.Flags().VarP(&serveFlags.jobs, "jobs", "j", "Jobs to run at the same time")
}
