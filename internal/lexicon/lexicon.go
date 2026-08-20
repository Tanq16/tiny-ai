// Package lexicon stores the vocabulary and known mishearings that shape a dictation.
// The recogniser is biased toward the vocabulary, and the polish pass reads both.
package lexicon

import (
	"encoding/json"
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"slices"
	"strings"
)

type Correction struct {
	From string `json:"from"`
	To   string `json:"to"`
}

type Lexicon struct {
	Vocabulary  []string     `json:"vocabulary"`
	Corrections []Correction `json:"corrections"`
}

// Load reads the lexicon, reporting a missing file as an empty one so a first run needs no setup.
func Load(path string) (Lexicon, error) {
	data, err := os.ReadFile(path)
	if errors.Is(err, fs.ErrNotExist) {
		return Lexicon{}.Normalize(), nil
	}
	if err != nil {
		return Lexicon{}, err
	}
	var lex Lexicon
	if err := json.Unmarshal(data, &lex); err != nil {
		return Lexicon{}, err
	}
	return lex.Normalize(), nil
}

// Save writes through a temporary file so an interrupted write cannot leave a truncated lexicon behind.
func Save(path string, lex Lexicon) error {
	data, err := json.MarshalIndent(lex.Normalize(), "", "  ")
	if err != nil {
		return err
	}
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, append(data, '\n'), 0o600); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

// Normalize trims every entry, drops the blanks, and keeps the first rule for any misheard phrase.
func (l Lexicon) Normalize() Lexicon {
	out := Lexicon{Vocabulary: []string{}, Corrections: []Correction{}}
	for _, term := range l.Vocabulary {
		if term = strings.TrimSpace(term); term != "" && !slices.Contains(out.Vocabulary, term) {
			out.Vocabulary = append(out.Vocabulary, term)
		}
	}
	seen := make(map[string]struct{}, len(l.Corrections))
	for _, c := range l.Corrections {
		from, to := strings.TrimSpace(c.From), strings.TrimSpace(c.To)
		// The recogniser's casing varies run to run, so one rule per phrase regardless of case.
		key := strings.ToLower(from)
		if _, dup := seen[key]; from == "" || to == "" || dup {
			continue
		}
		seen[key] = struct{}{}
		out.Corrections = append(out.Corrections, Correction{From: from, To: to})
	}
	return out
}

// Path names the lexicon file inside a data directory.
func Path(dataDir string) string { return filepath.Join(dataDir, "lexicon.json") }
