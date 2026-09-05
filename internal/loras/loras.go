package loras

import (
	"errors"
	"io"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"time"
)

const extension = ".safetensors"

var ErrInvalidName = errors.New("a LoRA needs a .safetensors file with a usable name")

var ErrNotFound = errors.New("no LoRA by that name")

type Entry struct {
	Name    string    `json:"name"`
	Bytes   int64     `json:"bytes"`
	AddedAt time.Time `json:"addedAt"`
}

func Dir(dataDir string) string { return filepath.Join(dataDir, "loras") }

func Name(filename string) (string, error) {
	base := strings.TrimSuffix(filepath.Base(filename), extension)
	cleaned := strings.Map(func(r rune) rune {
		switch {
		case r >= 'a' && r <= 'z', r >= 'A' && r <= 'Z', r >= '0' && r <= '9':
			return r
		case r == '-', r == '_', r == '.':
			return r
		default:
			return '-'
		}
	}, base)
	cleaned = strings.Trim(cleaned, "-.")
	if cleaned == "" {
		return "", ErrInvalidName
	}
	return cleaned, nil
}

func List(dir string) ([]Entry, error) {
	files, err := os.ReadDir(dir)
	if errors.Is(err, os.ErrNotExist) {
		return []Entry{}, nil
	}
	if err != nil {
		return nil, err
	}
	entries := make([]Entry, 0, len(files))
	for _, file := range files {
		if file.IsDir() || filepath.Ext(file.Name()) != extension {
			continue
		}
		info, err := file.Info()
		if err != nil {
			return nil, err
		}
		entries = append(entries, Entry{
			Name:    strings.TrimSuffix(file.Name(), extension),
			Bytes:   info.Size(),
			AddedAt: info.ModTime(),
		})
	}
	slices.SortFunc(entries, func(a, b Entry) int { return strings.Compare(a.Name, b.Name) })
	return entries, nil
}

func Save(dir, filename string, src io.Reader) (Entry, error) {
	if filepath.Ext(filename) != extension {
		return Entry{}, ErrInvalidName
	}
	name, err := Name(filename)
	if err != nil {
		return Entry{}, err
	}
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return Entry{}, err
	}
	target := filepath.Join(dir, name+extension)
	file, err := os.OpenFile(target, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o600)
	if err != nil {
		return Entry{}, err
	}
	size, err := io.Copy(file, src)
	if closeErr := file.Close(); err == nil {
		err = closeErr
	}
	if err != nil {
		os.Remove(target)
		return Entry{}, err
	}
	return Entry{Name: name, Bytes: size, AddedAt: time.Now()}, nil
}

func Delete(dir, name string) error {
	cleaned, err := Name(name)
	if err != nil {
		return err
	}
	if err := os.Remove(filepath.Join(dir, cleaned+extension)); err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return ErrNotFound
		}
		return err
	}
	return nil
}
