// Package catalog declares the tasks the suite can run and the parameters each one accepts.
// It is the single description the API, the frontend form, and the argv builder all read from,
// so adding a task is one entry here plus one Python script.
package catalog

import (
	"fmt"
	"slices"
)

type ParamType string

const (
	ParamFile     ParamType = "file"
	ParamText     ParamType = "text"
	ParamTextarea ParamType = "textarea"
	ParamSelect   ParamType = "select"
	ParamNumber   ParamType = "number"
	ParamBool     ParamType = "bool"
)

type Option struct {
	Value string `json:"value"`
	Label string `json:"label"`
}

type Param struct {
	Name     string    `json:"name"`
	Label    string    `json:"label"`
	Type     ParamType `json:"type"`
	Required bool      `json:"required,omitempty"`
	Default  string    `json:"default,omitempty"`
	Help     string    `json:"help,omitempty"`
	Options  []Option  `json:"options,omitempty"`
	Accept   string    `json:"accept,omitempty"`
	// Widget names a purpose-built frontend control, leaving the wire type of the parameter as declared.
	Widget string  `json:"widget,omitempty"`
	Min    float64 `json:"min,omitempty"`
	Max    float64 `json:"max,omitempty"`
	Step   float64 `json:"step,omitempty"`
	// VisibleWhen names another parameter and the value it must hold for this one to apply.
	VisibleWhen *Condition `json:"visibleWhen,omitempty"`
}

type Condition struct {
	Param  string `json:"param"`
	Equals string `json:"equals"`
}

type Task struct {
	ID          string  `json:"id"`
	Title       string  `json:"title"`
	Group       string  `json:"group"`
	Description string  `json:"description"`
	Engine      string  `json:"engine"`
	Icon        string  `json:"icon"`
	Project     string  `json:"project"`
	Params      []Param `json:"params"`
}

// Param returns the named parameter, reporting whether the task declares it.
func (t Task) Param(name string) (Param, bool) {
	i := slices.IndexFunc(t.Params, func(p Param) bool { return p.Name == name })
	if i < 0 {
		return Param{}, false
	}
	return t.Params[i], true
}

// All returns every task in display order.
func All() []Task { return slices.Clone(tasks) }

// Get resolves a task by its ID.
func Get(id string) (Task, error) {
	i := slices.IndexFunc(tasks, func(t Task) bool { return t.ID == id })
	if i < 0 {
		return Task{}, fmt.Errorf("unknown task %q", id)
	}
	return tasks[i], nil
}

// Groups returns the distinct task groups in display order.
func Groups() []string {
	var groups []string
	for _, t := range tasks {
		if !slices.Contains(groups, t.Group) {
			groups = append(groups, t.Group)
		}
	}
	return groups
}
