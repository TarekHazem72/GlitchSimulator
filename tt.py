import heapq
import itertools
import json
import tkinter as tk
from dataclasses import dataclass, field
from tkinter import ttk, filedialog, messagebox
from typing import Dict, List, Tuple, Optional

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure


@dataclass(order=True)
class Event:
    time: int
    priority: int
    wire_name: str = field(compare=False)
    value: int = field(compare=False)


class Wire:
    def __init__(self, name: str, initial: int = 0):
        self.name = name
        self.value = initial
        self.history: List[Tuple[int, int]] = [(0, initial)]
        self.listeners: List["Gate"] = []

    def connect(self, gate: "Gate") -> None:
        if gate not in self.listeners:
            self.listeners.append(gate)

    def set_value(self, time: int, value: int) -> bool:
        if value == self.value:
            return False
        
        self.value = value
        if not self.history or self.history[-1] != (time, value):
            self.history.append((time, value))
        return True

    def glitch_intervals(self, threshold: int = 2) -> List[Tuple[int, int]]:
        glitches = []
        for i in range(1, len(self.history)):
            t1, v1 = self.history[i - 1]
            t2, v2 = self.history[i]
            if v1 != v2 and (t2 - t1) <= threshold:
                glitches.append((t1, t2))
        return glitches


class Gate:
    def __init__(self, name: str, gate_type: str, inputs: List[str], output: str, delay: int):
        self.name = name
        self.gate_type = gate_type.upper()
        self.inputs = inputs
        self.output = output
        self.delay = max(0, delay)

    def logic(self, values: List[int]) -> int:
        # Replaced the massive if/else chain with a modern match/case
        match self.gate_type:
            case "AND":  return int(all(values))
            case "OR":   return int(any(values))
            case "NOT":  return int(not values[0])
            case "NAND": return int(not all(values))
            case "NOR":  return int(not any(values))
            case "XOR":  return sum(values) % 2
            case "XNOR": return 1 - (sum(values) % 2)
            case "BUF":  return values[0]
            case _: raise ValueError(f"Unknown gate type: {self.gate_type}")


class Simulator:
    def __init__(self, circuit: "Circuit"):
        self.circuit = circuit
        self.time = 0
        self._queue: List[Event] = []
        self._counter = itertools.count()  # Human way to handle tie-breakers deterministically
        self.log: List[str] = []

    def schedule(self, time: int, wire_name: str, value: int) -> None:
        heapq.heappush(self._queue, Event(time, next(self._counter), wire_name, value))

    def run(self, max_time: int = 100) -> List[str]:
        self.circuit.initialize_state(self)

        while self._queue:
            event = heapq.heappop(self._queue)
            if event.time > max_time:
                break
            
            self.time = event.time
            wire = self.circuit.wires.get(event.wire_name)
            
            if wire and wire.set_value(event.time, event.value):
                self.log.append(f"t={event.time:>4}  {wire.name} -> {event.value}")
                self.circuit.propagate_from_wire(wire.name, self)

        return self.log


class Circuit:
    def __init__(self):
        self.wires: Dict[str, Wire] = {}
        self.gates: List[Gate] = []
        self.primary_inputs: List[str] = []
        self.primary_outputs: List[str] = []

    def ensure_wire(self, name: str, initial: int = 0) -> Wire:
        if name not in self.wires:
            self.wires[name] = Wire(name, initial)
        return self.wires[name]

    def add_input(self, name: str, initial: int = 0) -> None:
        self.ensure_wire(name, initial)
        if name not in self.primary_inputs:
            self.primary_inputs.append(name)

    def add_output(self, name: str) -> None:
        self.ensure_wire(name)
        if name not in self.primary_outputs:
            self.primary_outputs.append(name)

    def add_gate(self, gate: Gate) -> None:
        self.gates.append(gate)
        self.ensure_wire(gate.output)
        for inp in gate.inputs:
            self.ensure_wire(inp).connect(gate)

    def recompute_gate(self, gate: Gate, sim: Simulator) -> None:
        values = [self.wires[name].value for name in gate.inputs]
        new_value = gate.logic(values)
        if new_value != self.wires[gate.output].value:
            sim.schedule(sim.time + gate.delay, gate.output, new_value)

    def propagate_from_wire(self, wire_name: str, sim: Simulator) -> None:
        for gate in self.wires[wire_name].listeners:
            self.recompute_gate(gate, sim)

    def initialize_state(self, sim: Simulator) -> None:
        # Replaced the hallucinated if/else block with a proper topological sort (Kahn's Algorithm)
        in_degree = {g.name: 0 for g in self.gates}
        gate_map = {g.name: g for g in self.gates}
        wire_to_gates = {w: [] for w in self.wires}

        for g in self.gates:
            for inp in g.inputs:
                wire_to_gates[inp].append(g)
                # Only internal wire dependencies increment the degree
                if any(other.output == inp for other in self.gates):
                    in_degree[g.name] += 1

        queue = [g for name, g in gate_map.items() if in_degree[name] == 0]

        while queue:
            gate = queue.pop(0)
            self.recompute_gate(gate, sim)
            for dependent in wire_to_gates.get(gate.output, []):
                in_degree[dependent.name] -= 1
                if in_degree[dependent.name] == 0:
                    queue.append(dependent)

    def to_dict(self) -> dict:
        return {
            "inputs": self.primary_inputs,
            "outputs": self.primary_outputs,
            "wires": {name: wire.value for name, wire in self.wires.items()},
            "gates": [{"name": g.name, "type": g.gate_type, "inputs": g.inputs, "output": g.output, "delay": g.delay} for g in self.gates],
        }

    @staticmethod
    def from_dict(data: dict) -> "Circuit":
        c = Circuit()
        for name in data.get("inputs", []):
            c.add_input(name, int(data.get("wires", {}).get(name, 0)))
        for name in data.get("outputs", []):
            c.add_output(name)
        for wname, wval in data.get("wires", {}).items():
            c.ensure_wire(wname, int(wval))
        for g in data.get("gates", []):
            c.add_gate(Gate(g["name"], g["type"], list(g["inputs"]), g["output"], int(g["delay"])))
        return c


GATE_TYPES = ["AND", "OR", "NOT", "NAND", "NOR", "XOR", "XNOR", "BUF"]

def build_sample_circuit() -> Circuit:
    c = Circuit()
    for name, initial in [("A", 0), ("B", 1), ("C", 0), ("D", 0), ("OUT", 0), ("TAP", 0)]:
        c.add_input(name, initial) if name in {"A", "B"} else c.ensure_wire(name, initial)
    c.add_output("OUT")
    c.add_output("TAP")

    c.add_gate(Gate("G1", "AND", ["A", "B"], "C", delay=4))
    c.add_gate(Gate("G2", "NOT", ["A"], "D", delay=1))
    c.add_gate(Gate("G3", "OR", ["C", "D"], "OUT", delay=2))
    c.add_gate(Gate("G4", "BUF", ["OUT"], "TAP", delay=1))
    return c


class GlitchSimulatorApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Glitch Detection Simulator")
        self.root.geometry("1200x760")

        self.circuit = build_sample_circuit()
        self.sim_result_log: List[str] = []
        self.stimuli: List[Tuple[int, str, int]] = []

        self._build_styles()
        self._build_layout()
        self._refresh_all_views()

    def _build_styles(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TButton", padding=6)
        style.configure("TLabel", padding=3)
        style.configure("TLabelframe", padding=8)
        style.configure("TLabelframe.Label", font=("Segoe UI", 10, "bold"))

    # Extracted massive layout block into logical, human-readable helper components
    def _build_layout(self) -> None:
        self.main = ttk.Frame(self.root, padding=12)
        self.main.pack(fill="both", expand=True)

        self.left = ttk.Frame(self.main)
        self.left.pack(side="left", fill="y", padx=(0, 12))

        self.center = ttk.Frame(self.main)
        self.center.pack(side="left", fill="both", expand=True)

        self._build_builder_panel(self.left)
        self._build_stimuli_panel(self.left)
        self._build_simulation_panel(self.left)
        self._build_center_views(self.center)

    def _build_builder_panel(self, parent: ttk.Frame) -> None:
        build_box = ttk.LabelFrame(parent, text="Circuit Builder")
        build_box.pack(fill="x", pady=(0, 12))

        self.gate_name_var = tk.StringVar(value="G_NEW")
        self.gate_type_var = tk.StringVar(value="AND")
        self.gate_inputs_var = tk.StringVar(value="A,B")
        self.gate_output_var = tk.StringVar(value="Y")
        self.gate_delay_var = tk.StringVar(value="2")

        fields = [
            ("Gate name", self.gate_name_var),
            ("Gate type", self.gate_type_var),
            ("Inputs (comma)", self.gate_inputs_var),
            ("Output", self.gate_output_var),
            ("Delay", self.gate_delay_var),
        ]

        for label, var in fields:
            row = ttk.Frame(build_box)
            row.pack(fill="x", pady=3)
            ttk.Label(row, text=label, width=15).pack(side="left")
            
            if label == "Gate type":
                ttk.Combobox(row, textvariable=var, values=GATE_TYPES, state="readonly", width=20).pack(side="left", fill="x", expand=True)
            else:
                ttk.Entry(row, textvariable=var, width=24).pack(side="left", fill="x", expand=True)

        ttk.Button(build_box, text="Add Gate", command=self.add_gate_from_form).pack(fill="x", pady=(8, 4))
        ttk.Button(build_box, text="Load Sample", command=self.load_sample).pack(fill="x", pady=4)
        ttk.Button(build_box, text="Save Circuit", command=self.save_circuit).pack(fill="x", pady=4)
        ttk.Button(build_box, text="Load Circuit", command=self.load_circuit).pack(fill="x", pady=4)

    def _build_stimuli_panel(self, parent: ttk.Frame) -> None:
        stim_box = ttk.LabelFrame(parent, text="Inputs & Stimuli")
        stim_box.pack(fill="x", pady=(0, 12))

        self.stim_time_var = tk.StringVar(value="1")
        self.stim_wire_var = tk.StringVar(value="A")
        self.stim_value_var = tk.StringVar(value="1")

        stim_row = ttk.Frame(stim_box)
        stim_row.pack(fill="x", pady=(8, 3))
        ttk.Label(stim_row, text="Time", width=10).pack(side="left")
        ttk.Entry(stim_row, textvariable=self.stim_time_var, width=8).pack(side="left")
        ttk.Label(stim_row, text="Wire", width=8).pack(side="left")
        ttk.Entry(stim_row, textvariable=self.stim_wire_var, width=8).pack(side="left")
        ttk.Label(stim_row, text="Value", width=8).pack(side="left")
        ttk.Combobox(stim_row, textvariable=self.stim_value_var, values=["0", "1"], state="readonly", width=6).pack(side="left")
        
        ttk.Button(stim_box, text="Add Stimulus", command=self.add_stimulus_from_form).pack(fill="x", pady=(6, 4))

        self.stimuli_tree = ttk.Treeview(stim_box, columns=("time", "wire", "value"), show="headings", height=6)
        for col, text in [("time", "Time"), ("wire", "Wire"), ("value", "Value")]:
            self.stimuli_tree.heading(col, text=text)
            self.stimuli_tree.column(col, width=70, anchor="center")
        self.stimuli_tree.pack(fill="x", pady=(4, 0))

        ttk.Button(stim_box, text="Remove Selected Stimulus", command=self.remove_selected_stimulus).pack(fill="x", pady=(6, 0))
        ttk.Button(stim_box, text="Clear Stimuli", command=self.clear_stimuli).pack(fill="x", pady=4)

    def _build_simulation_panel(self, parent: ttk.Frame) -> None:
        sim_box = ttk.LabelFrame(parent, text="Simulation")
        sim_box.pack(fill="x", pady=(0, 12))

        self.max_time_var = tk.StringVar(value="25")
        self.glitch_threshold_var = tk.StringVar(value="2")

        row1 = ttk.Frame(sim_box)
        row1.pack(fill="x", pady=3)
        ttk.Label(row1, text="Max time", width=15).pack(side="left")
        ttk.Entry(row1, textvariable=self.max_time_var, width=10).pack(side="left")

        row2 = ttk.Frame(sim_box)
        row2.pack(fill="x", pady=3)
        ttk.Label(row2, text="Glitch window", width=15).pack(side="left")
        ttk.Entry(row2, textvariable=self.glitch_threshold_var, width=10).pack(side="left")

        ttk.Button(sim_box, text="Run Simulation", command=self.run_simulation).pack(fill="x", pady=(8, 4))
        ttk.Button(sim_box, text="Plot Waveforms", command=self.plot_waveforms).pack(fill="x", pady=4)
        ttk.Button(sim_box, text="Export Results", command=self.export_results).pack(fill="x", pady=4)

    def _build_center_views(self, parent: ttk.Frame) -> None:
        top_center = ttk.Frame(parent)
        top_center.pack(fill="both", expand=True)

        circuit_box = ttk.LabelFrame(top_center, text="Current Circuit")
        circuit_box.pack(side="left", fill="both", expand=True, padx=(0, 8))

        self.circuit_tree = ttk.Treeview(circuit_box, columns=("type", "inputs", "output", "delay"), show="headings", height=12)
        for col, text, width in [("type", "Type", 90), ("inputs", "Inputs", 180), ("output", "Output", 100), ("delay", "Delay", 70)]:
            self.circuit_tree.heading(col, text=text)
            self.circuit_tree.column(col, width=width, anchor="center")
        self.circuit_tree.pack(fill="both", expand=True)

        self.wire_tree = ttk.Treeview(circuit_box, columns=("value", "history"), show="headings", height=8)
        for col, text, width in [("value", "Value", 70), ("history", "History", 360)]:
            self.wire_tree.heading(col, text=text)
            self.wire_tree.column(col, width=width, anchor="w")
        self.wire_tree.pack(fill="both", expand=True, pady=(10, 0))

        right_box = ttk.LabelFrame(top_center, text="Simulation Log & Glitches")
        right_box.pack(side="right", fill="both", expand=True)

        self.result_text = tk.Text(right_box, wrap="word", height=28, width=42)
        self.result_text.pack(fill="both", expand=True)

        plot_box = ttk.LabelFrame(parent, text="Waveforms")
        plot_box.pack(fill="both", expand=True, pady=(12, 0))

        self.fig = Figure(figsize=(9, 3.8), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.fig, master=plot_box)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

    def _refresh_all_views(self) -> None:
        self._refresh_circuit_view()
        self._refresh_wire_view()
        self._refresh_stimuli_view()
        self._refresh_result_text("Ready. Load the sample or build your own circuit, then run the simulation.\n")
        self.plot_waveforms()

    def _refresh_circuit_view(self) -> None:
        self.circuit_tree.delete(*self.circuit_tree.get_children())
        for gate in self.circuit.gates:
            self.circuit_tree.insert("", "end", values=(gate.gate_type, ", ".join(gate.inputs), gate.output, gate.delay))

    def _refresh_wire_view(self) -> None:
        self.wire_tree.delete(*self.wire_tree.get_children())
        for name in sorted(self.circuit.wires.keys()):
            wire = self.circuit.wires[name]
            hist = " | ".join(f"({t},{v})" for t, v in wire.history)
            self.wire_tree.insert("", "end", values=(f"{wire.value}", hist), text=name)

    def _refresh_stimuli_view(self) -> None:
        self.stimuli_tree.delete(*self.stimuli_tree.get_children())
        for idx, (time, wire, value) in enumerate(self.stimuli):
            self.stimuli_tree.insert("", "end", iid=str(idx), values=(time, wire, value))

    def _refresh_result_text(self, text: str, append: bool = False) -> None:
        if not append:
            self.result_text.delete("1.0", tk.END)
        self.result_text.insert(tk.END, text)
        self.result_text.see(tk.END)

    def _validate_gate(self, gate_type: str, inputs: List[str]) -> Optional[str]:
        if gate_type in {"NOT", "BUF"} and len(inputs) != 1:
            return f"{gate_type} gates must have exactly one input."
        if gate_type not in {"NOT", "BUF"} and len(inputs) < 2:
            return f"{gate_type} gates need at least two inputs."
        if not inputs or any(not x for x in inputs):
            return "Every gate input must be named."
        return None

    def add_gate_from_form(self) -> None:
        try:
            name = self.gate_name_var.get().strip()
            gate_type = self.gate_type_var.get().strip().upper()
            inputs = [s.strip() for s in self.gate_inputs_var.get().split(",") if s.strip()]
            output = self.gate_output_var.get().strip()
            delay = int(self.gate_delay_var.get().strip())
        except ValueError:
            messagebox.showerror("Invalid gate", "Please check the gate fields.")
            return

        if not name or not output:
            messagebox.showerror("Invalid gate", "Gate name and output are required.")
            return
        if gate_type not in GATE_TYPES:
            messagebox.showerror("Invalid gate", f"Unsupported gate type: {gate_type}")
            return
            
        err = self._validate_gate(gate_type, inputs)
        if err:
            messagebox.showerror("Invalid gate", err)
            return

        if any(g.name == name for g in self.circuit.gates):
            messagebox.showerror("Invalid gate", f"A gate named '{name}' already exists.")
            return

        for inp in inputs:
            self.circuit.ensure_wire(inp)
        
        self.circuit.ensure_wire(output)
        self.circuit.add_gate(Gate(name, gate_type, inputs, output, delay))
        
        self._refresh_circuit_view()
        self._refresh_wire_view()
        self._refresh_result_text(f"Added gate {name} ({gate_type}).\n", append=True)

    def add_stimulus_from_form(self) -> None:
        try:
            time = int(self.stim_time_var.get().strip())
            wire = self.stim_wire_var.get().strip()
            value = int(self.stim_value_var.get().strip())
        except ValueError:
            messagebox.showerror("Invalid stimulus", "Please enter a valid time, wire, and value.")
            return

        if not wire:
            messagebox.showerror("Invalid stimulus", "Wire name is required.")
            return
            
        self.circuit.ensure_wire(wire)
        self.stimuli.append((time, wire, 1 if value else 0))
        self.stimuli.sort()
        self._refresh_stimuli_view()

    def remove_selected_stimulus(self) -> None:
        selected = self.stimuli_tree.selection()
        if not selected:
            return
        
        idx = int(selected[0])
        if 0 <= idx < len(self.stimuli):
            self.stimuli.pop(idx)
        self._refresh_stimuli_view()

    def clear_stimuli(self) -> None:
        self.stimuli.clear()
        self._refresh_stimuli_view()

    def load_sample(self) -> None:
        self.circuit = build_sample_circuit()
        self.stimuli = [(1, "A", 1), (3, "A", 0), (5, "B", 0), (8, "A", 1)]
        self._refresh_all_views()
        self._refresh_result_text("Loaded sample circuit and sample stimuli.\n")

    def run_simulation(self) -> None:
        try:
            max_time = int(self.max_time_var.get().strip())
            glitch_threshold = int(self.glitch_threshold_var.get().strip())
        except ValueError:
            messagebox.showerror("Invalid simulation settings", "Please check the simulation fields.")
            return

        if not self.circuit.gates:
            messagebox.showwarning("No gates", "Add at least one gate before running the simulation.")
            return

        # Reset state history before running
        for wire in self.circuit.wires.values():
            wire.history = [(0, wire.value)]

        sim = Simulator(self.circuit)

        for time, wire, value in self.stimuli:
            sim.schedule(time, wire, value)

        if not self.stimuli:
            for name in self.circuit.primary_inputs:
                sim.schedule(0, name, self.circuit.wires[name].value)

        log = sim.run(max_time=max_time)
        self.sim_result_log = list(log)

        glitches = []
        for name in sorted(self.circuit.wires.keys()):
            intervals = self.circuit.wires[name].glitch_intervals(threshold=glitch_threshold)
            for t1, t2 in intervals:
                glitches.append(f"{name}: rapid transition between t={t1} and t={t2}")

        text_lines = ["Simulation log:\n"]
        text_lines.extend(line + "\n" for line in log) if log else text_lines.append("(No signal changes occurred.)\n")
        
        text_lines.append("\nGlitch report:\n")
        text_lines.extend(line + "\n" for line in glitches) if glitches else text_lines.append("No glitches detected.\n")

        self._refresh_result_text("".join(text_lines))
        self._refresh_circuit_view()
        self._refresh_wire_view()
        self.plot_waveforms()

    def plot_waveforms(self) -> None:
        self.ax.clear()

        sorted_wires = [self.circuit.wires[name] for name in sorted(self.circuit.wires.keys())]
        if not sorted_wires:
            self.ax.set_title("No wires to plot")
            self.canvas.draw_idle()
            return

        max_hist_time = max((wire.history[-1][0] for wire in sorted_wires if wire.history), default=0)
        max_time = max(max_hist_time, int(self.max_time_var.get().strip() or 20))
        lane_gap = 2.2

        for idx, wire in enumerate(sorted_wires):
            if not wire.history:
                times, values = [0, max_time], [0, 0]
            else:
                times, values = [wire.history[0][0]], [wire.history[0][1]]
                last_v = values[0]
                for t, v in wire.history[1:]:
                    times.extend([t, t])
                    values.extend([last_v, v])
                    last_v = v
                if times[-1] < max_time:
                    times.extend([max_time])
                    values.extend([last_v])

            offset = idx * lane_gap
            values = [v + offset for v in values]
            
            self.ax.step(times, values, where="post", linewidth=2)
            self.ax.text(max_time + 0.3, offset + 0.5, wire.name, va="center", fontsize=9)

            for t1, t2 in wire.glitch_intervals(threshold=int(self.glitch_threshold_var.get().strip() or 2)):
                self.ax.axvspan(t1, t2, alpha=0.15, color='red')

        self.ax.set_xlim(0, max_time + 2)
        self.ax.set_ylim(-0.5, len(sorted_wires) * lane_gap + 0.5)
        self.ax.set_yticks([])
        self.ax.set_xlabel("Time")
        self.ax.set_title("Digital Waveforms")
        self.ax.grid(True, axis="x", linestyle="--", alpha=0.3)
        self.fig.tight_layout()
        self.canvas.draw_idle()

    def export_results(self) -> None:
        payload = {
            "circuit": self.circuit.to_dict(),
            "stimuli": self.stimuli,
            "log": self.sim_result_log,
            "wire_histories": {name: wire.history for name, wire in self.circuit.wires.items()},
        }
        path = filedialog.asksaveasfilename(title="Export Results", defaultextension=".json", filetypes=[("JSON files", "*.json")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            messagebox.showinfo("Export complete", f"Saved results to:\n{path}")
        except Exception as exc:
            messagebox.showerror("Export failed", str(exc))

    def save_circuit(self) -> None:
        path = filedialog.asksaveasfilename(title="Save Circuit", defaultextension=".json", filetypes=[("JSON files", "*.json")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.circuit.to_dict(), f, indent=2)
            messagebox.showinfo("Saved", f"Circuit saved to:\n{path}")
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc))

    def load_circuit(self) -> None:
        path = filedialog.askopenfilename(title="Load Circuit", filetypes=[("JSON files", "*.json")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.circuit = Circuit.from_dict(data)
            self._refresh_all_views()
            self._refresh_result_text(f"Loaded circuit from {path}\n")
        except Exception as exc:
            messagebox.showerror("Load failed", str(exc))


if __name__ == "__main__":
    root = tk.Tk()
    app = GlitchSimulatorApp(root)
    root.mainloop()