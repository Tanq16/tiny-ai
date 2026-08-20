package catalog

import (
	"os"
	"path/filepath"
	"slices"
	"strconv"
	"strings"
	"testing"
)

func TestTaskDefinitionsAreConsistent(t *testing.T) {
	var ids []string
	for _, task := range All() {
		t.Run(task.ID, func(t *testing.T) {
			if slices.Contains(ids, task.ID) {
				t.Errorf("duplicate task id %q", task.ID)
			}
			if !strings.HasSuffix(task.Script, ".py") {
				t.Errorf("script %q is not a python file", task.Script)
			}
			if task.Group == "" || task.Title == "" || task.Icon == "" {
				t.Errorf("task %q is missing a group, title or icon", task.ID)
			}

			var names []string
			for _, p := range task.Params {
				if slices.Contains(names, p.Name) {
					t.Errorf("duplicate param %q", p.Name)
				}
				names = append(names, p.Name)
				checkParam(t, task, p)
			}
		})
		ids = append(ids, task.ID)
	}
}

func checkParam(t *testing.T, task Task, p Param) {
	t.Helper()
	if p.Label == "" {
		t.Errorf("param %q has no label", p.Name)
	}
	if strings.ContainsAny(p.Name, " _") {
		t.Errorf("param %q must be a flag-shaped name", p.Name)
	}

	switch p.Type {
	case ParamSelect:
		if len(p.Options) == 0 {
			t.Errorf("select param %q has no options", p.Name)
		}
		if p.Default != "" && !slices.ContainsFunc(p.Options, func(o Option) bool { return o.Value == p.Default }) {
			t.Errorf("select param %q defaults to %q, which is not one of its options", p.Name, p.Default)
		}
	case ParamNumber:
		if p.Max <= p.Min {
			t.Errorf("number param %q has an empty range [%v,%v]", p.Name, p.Min, p.Max)
		}
		if p.Default == "" {
			t.Errorf("number param %q has no default", p.Name)
			return
		}
		v, err := strconv.ParseFloat(p.Default, 64)
		if err != nil {
			t.Errorf("number param %q has a non-numeric default %q", p.Name, p.Default)
			return
		}
		if v < p.Min || v > p.Max {
			t.Errorf("number param %q defaults to %v, outside [%v,%v]", p.Name, v, p.Min, p.Max)
		}
	case ParamBool:
		if p.Default != "" && p.Default != "true" && p.Default != "false" {
			t.Errorf("bool param %q has a non-boolean default %q", p.Name, p.Default)
		}
	case ParamFile, ParamText, ParamTextarea:
	default:
		t.Errorf("param %q has an unknown type %q", p.Name, p.Type)
	}

	if p.VisibleWhen == nil {
		return
	}
	target, ok := task.Param(p.VisibleWhen.Param)
	if !ok {
		t.Errorf("param %q is gated on %q, which the task does not declare", p.Name, p.VisibleWhen.Param)
		return
	}
	if target.Type == ParamSelect &&
		!slices.ContainsFunc(target.Options, func(o Option) bool { return o.Value == p.VisibleWhen.Equals }) {
		t.Errorf("param %q is gated on %s=%q, which is not a value %s can hold",
			p.Name, target.Name, p.VisibleWhen.Equals, target.Name)
	}
}

// The catalog names the script the runner executes, so a typo here is a task that
// only fails once someone submits it.
func TestEveryTaskScriptExists(t *testing.T) {
	root := filepath.Join("..", "..")
	for _, task := range All() {
		if _, err := os.Stat(filepath.Join(root, task.Script)); err != nil {
			t.Errorf("task %q names %s, which does not exist: %v", task.ID, task.Script, err)
		}
	}
}

func TestGetUnknownTask(t *testing.T) {
	if _, err := Get("nope"); err == nil {
		t.Error("Get(\"nope\") returned no error")
	}
	if _, err := Get(""); err == nil {
		t.Error("Get(\"\") returned no error")
	}
}
