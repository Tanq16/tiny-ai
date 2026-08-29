package runner

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"path/filepath"
	"strings"

	"github.com/Tanq16/tiny-ai/internal/catalog"
)

var (
	ErrChatBusy       = errors.New("a chat is already open")
	ErrNotInteractive = errors.New("this job is not a chat")
	ErrChatNotReady   = errors.New("the chat is still starting")
)

type Message struct {
	Text  string
	Files []Upload
}

type chatCommand struct {
	Text   string   `json:"text"`
	Images []string `json:"images,omitzero"`
	Audio  []string `json:"audio,omitzero"`
}

func attachmentKind(name string) string {
	switch strings.ToLower(filepath.Ext(name)) {
	case ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tiff":
		return "image"
	case ".mp3", ".wav", ".flac", ".m4a", ".opus", ".ogg", ".aac", ".webm", ".mp4":
		return "audio"
	}
	return ""
}

func (r *Runner) startChat(task catalog.Task, sub Submission) (Job, error) {
	r.chatMu.Lock()
	defer r.chatMu.Unlock()

	if live := r.chatRec; live != nil && !live.snapshot(false).State.Terminal() {
		return Job{}, ErrChatBusy
	}
	rec, snap, err := r.prepare(task, sub)
	if err != nil {
		return Job{}, err
	}
	select {
	case r.chatQueue <- rec:
	default:
		rec.fail(ErrChatBusy.Error())
		return snap, ErrChatBusy
	}
	r.chatRec = rec
	return snap, nil
}

func (r *Runner) Send(id string, msg Message) (Job, error) {
	rec, ok := r.lookup(id)
	if !ok {
		return Job{}, ErrJobNotFound
	}
	msg.Text = strings.TrimSpace(msg.Text)
	if msg.Text == "" && len(msg.Files) == 0 {
		return Job{}, &ValidationError{Msg: "a message needs text or an attachment"}
	}
	for _, up := range msg.Files {
		if attachmentKind(up.Filename) == "" {
			return Job{}, &ValidationError{Msg: fmt.Sprintf("%q is not an image or an audio file", up.Filename)}
		}
	}

	rec.sendMu.Lock()
	defer rec.sendMu.Unlock()

	stdin, err := rec.chatPipe()
	if err != nil {
		return Job{}, err
	}

	rec.mu.Lock()
	rec.turns++
	turn, inDir := rec.turns, rec.inDir
	rec.mu.Unlock()

	command := chatCommand{Text: msg.Text}
	var names []string
	for i, up := range msg.Files {
		name := fmt.Sprintf("%03d-%d-%s", turn, i, sanitizeFilename(up.Filename))
		dest := filepath.Join(inDir, name)
		if _, err := saveUpload(dest, up.Content); err != nil {
			return Job{}, err
		}
		names = append(names, name)
		if attachmentKind(name) == "image" {
			command.Images = append(command.Images, dest)
		} else {
			command.Audio = append(command.Audio, dest)
		}
	}

	line, err := json.Marshal(command)
	if err != nil {
		return Job{}, err
	}
	rec.apply(Event{Event: EventChat, Role: "user", Message: msg.Text, Files: names})
	if _, err := stdin.Write(append(line, '\n')); err != nil {
		return Job{}, err
	}
	return rec.snapshot(false), nil
}

func (r *Runner) Finish(id string) error {
	rec, ok := r.lookup(id)
	if !ok {
		return ErrJobNotFound
	}
	rec.sendMu.Lock()
	defer rec.sendMu.Unlock()
	return rec.closeChat()
}

func (rec *record) chatPipe() (io.WriteCloser, error) {
	rec.mu.Lock()
	defer rec.mu.Unlock()
	switch {
	case !rec.interactive:
		return nil, ErrNotInteractive
	case rec.snap.State.Terminal():
		return nil, ErrJobFinished
	case rec.stdin == nil:
		return nil, ErrChatNotReady
	}
	return rec.stdin, nil
}

func (rec *record) closeChat() error {
	rec.mu.Lock()
	stdin := rec.stdin
	rec.stdin = nil
	interactive, terminal := rec.interactive, rec.snap.State.Terminal()
	rec.mu.Unlock()

	switch {
	case !interactive:
		return ErrNotInteractive
	case stdin != nil:
		return stdin.Close()
	case terminal:
		return ErrJobFinished
	}
	return ErrChatNotReady
}
