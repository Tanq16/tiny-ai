package lexicon

import (
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

func TestNormalize(t *testing.T) {
	tests := []struct {
		name string
		in   Lexicon
		want Lexicon
	}{
		{
			name: "empty stays an empty list rather than a null",
			in:   Lexicon{},
			want: Lexicon{Vocabulary: []string{}, Corrections: []Correction{}},
		},
		{
			name: "terms are trimmed and blanks dropped",
			in:   Lexicon{Vocabulary: []string{"  MLX ", "", "   ", "Tanq16"}},
			want: Lexicon{Vocabulary: []string{"MLX", "Tanq16"}, Corrections: []Correction{}},
		},
		{
			name: "duplicate terms collapse to the first",
			in:   Lexicon{Vocabulary: []string{"MLX", "MLX", " MLX "}},
			want: Lexicon{Vocabulary: []string{"MLX"}, Corrections: []Correction{}},
		},
		{
			name: "a term differing only by case is its own spelling",
			in:   Lexicon{Vocabulary: []string{"MLX", "mlx"}},
			want: Lexicon{Vocabulary: []string{"MLX", "mlx"}, Corrections: []Correction{}},
		},
		{
			name: "a correction missing either side is dropped",
			in: Lexicon{Corrections: []Correction{
				{From: "tank sixteen", To: ""},
				{From: "  ", To: "Tanq16"},
				{From: " tank sixteen ", To: " Tanq16 "},
			}},
			want: Lexicon{Vocabulary: []string{}, Corrections: []Correction{{From: "tank sixteen", To: "Tanq16"}}},
		},
		{
			name: "one rule per misheard phrase regardless of case",
			in: Lexicon{Corrections: []Correction{
				{From: "tank sixteen", To: "Tanq16"},
				{From: "Tank Sixteen", To: "Tank16"},
			}},
			want: Lexicon{Vocabulary: []string{}, Corrections: []Correction{{From: "tank sixteen", To: "Tanq16"}}},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := tt.in.Normalize(); !reflect.DeepEqual(got, tt.want) {
				t.Errorf("Normalize() = %+v, want %+v", got, tt.want)
			}
		})
	}
}

func TestLoad(t *testing.T) {
	tests := []struct {
		name    string
		write   string
		want    Lexicon
		wantErr bool
	}{
		{
			name: "a missing file reads as an empty lexicon",
			want: Lexicon{Vocabulary: []string{}, Corrections: []Correction{}},
		},
		{
			name:    "malformed JSON is an error rather than a silent reset",
			write:   "{not json",
			wantErr: true,
		},
		{
			name:  "a stored lexicon comes back normalized",
			write: `{"vocabulary":[" MLX ","MLX"],"corrections":[{"from":"tank sixteen","to":"Tanq16"}]}`,
			want: Lexicon{
				Vocabulary:  []string{"MLX"},
				Corrections: []Correction{{From: "tank sixteen", To: "Tanq16"}},
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			path := Path(t.TempDir())
			if tt.write != "" {
				if err := os.WriteFile(path, []byte(tt.write), 0o600); err != nil {
					t.Fatalf("WriteFile() = %v", err)
				}
			}
			got, err := Load(path)
			if (err != nil) != tt.wantErr {
				t.Fatalf("Load() err = %v, wantErr %v", err, tt.wantErr)
			}
			if err == nil && !reflect.DeepEqual(got, tt.want) {
				t.Errorf("Load() = %+v, want %+v", got, tt.want)
			}
		})
	}
}

func TestSaveNormalizesAndKeepsThePrivateMode(t *testing.T) {
	path := Path(t.TempDir())
	in := Lexicon{Vocabulary: []string{" MLX ", "MLX", ""}, Corrections: []Correction{{From: "a", To: ""}}}
	if err := Save(path, in); err != nil {
		t.Fatalf("Save() = %v", err)
	}

	got, err := Load(path)
	if err != nil {
		t.Fatalf("Load() = %v", err)
	}
	want := Lexicon{Vocabulary: []string{"MLX"}, Corrections: []Correction{}}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("Load() after Save() = %+v, want %+v", got, want)
	}

	info, err := os.Stat(path)
	if err != nil {
		t.Fatalf("Stat() = %v", err)
	}
	if info.Mode().Perm() != 0o600 {
		t.Errorf("mode = %v, want 600", info.Mode().Perm())
	}
	if _, err := os.Stat(filepath.Join(filepath.Dir(path), "lexicon.json.tmp")); !os.IsNotExist(err) {
		t.Error("Save() left its temporary file behind")
	}
}
