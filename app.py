"""
Quantum Lottery Picker - Backend API
Uses Qiskit to generate truly random lottery numbers via quantum superposition.
"""

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from qiskit import QuantumCircuit
from qiskit_aer import Aer
import math
import time
import random
import base64
import io
import sqlite3
import os
from datetime import datetime

# Optional imports for advanced features
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from qiskit.visualization import circuit_drawer
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False

try:
    from scipy.stats import chisquare
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False

app = Flask(__name__)
CORS(app)

# ─────────────────────────────────────────────
#  Core Quantum Functions
# ─────────────────────────────────────────────

def quantum_random_int(n_bits: int) -> int:
    """
    Generate a random integer using a quantum circuit.
    Places all qubits in superposition via Hadamard gates,
    then collapses to a random classical bitstring on measurement.
    """
    qc = QuantumCircuit(n_bits, n_bits)

    # Apply Hadamard to every qubit → equal superposition of all states
    for i in range(n_bits):
        qc.h(i)

    qc.measure(range(n_bits), range(n_bits))

    backend = Aer.get_backend("qasm_simulator")
    job = backend.run(qc, shots=1)
    result = job.result()
    counts = result.get_counts()

    # Extract the measured bitstring and convert to integer
    bitstring = list(counts.keys())[0]
    return int(bitstring, 2)


def quantum_lottery_pick(count: int = 6, max_num: int = 49) -> list[int]:
    """
    Pick 'count' unique numbers from 1..max_num using quantum randomness.
    Uses rejection sampling to stay in range while ensuring uniform distribution.
    """
    n_bits = math.ceil(math.log2(max_num + 1))
    numbers = set()
    max_attempts = count * 200  # safety ceiling

    for _ in range(max_attempts):
        if len(numbers) == count:
            break
        num = quantum_random_int(n_bits)
        if 1 <= num <= max_num:
            numbers.add(num)

    return sorted(list(numbers))


def quantum_probability_distribution(shots: int = 512) -> dict:
    """
    Run a multi-qubit circuit with many shots to show probability distribution.
    Uses 4 qubits to demonstrate 16 possible quantum states collapsing to 0/1.
    Returns counts of '0' and '1' outcomes across all qubits.
    """
    n_qubits = 4
    qc = QuantumCircuit(n_qubits, n_qubits)
    for i in range(n_qubits):
        qc.h(i)
    qc.measure(range(n_qubits), range(n_qubits))

    backend = Aer.get_backend("qasm_simulator")
    job = backend.run(qc, shots=shots)
    result = job.result()
    raw_counts = result.get_counts()

    # Aggregate bit-level 0/1 distribution across all qubits and shots
    zero_count = 0
    one_count = 0
    state_distribution = {}

    for bitstring, count in raw_counts.items():
        state_distribution[bitstring] = count
        zero_count += bitstring.count("0") * count
        one_count += bitstring.count("1") * count

    total = zero_count + one_count
    return {
        "zero_probability": round(zero_count / total, 4),
        "one_probability": round(one_count / total, 4),
        "zero_count": zero_count,
        "one_count": one_count,
        "state_distribution": dict(
            sorted(state_distribution.items(), key=lambda x: -x[1])[:16]
        ),
        "total_shots": shots,
    }


def quantum_entangled_pair() -> dict:
    """
    Create a Bell state (entangled qubit pair) and measure both qubits.
    Demonstrates quantum entanglement: both qubits always match.
    """
    qc = QuantumCircuit(2, 2)
    qc.h(0)          # Superposition on qubit 0
    qc.cx(0, 1)      # CNOT: entangle qubit 1 with qubit 0
    qc.measure([0, 1], [0, 1])

    backend = Aer.get_backend("qasm_simulator")
    job = backend.run(qc, shots=200)
    result = job.result()
    counts = result.get_counts()

    return {
        "counts": counts,
        "explanation": "In a Bell state, both qubits always collapse to the same value — "
                       "demonstrating quantum entanglement.",
    }


# ─────────────────────────────────────────────
#  Feature 1 & 2: History DB + Frequency Store
# ─────────────────────────────────────────────

DB_PATH = os.path.join(os.path.dirname(__file__), "lottery_history.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS draws (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            ts       TEXT NOT NULL,
            numbers  TEXT NOT NULL,
            max_num  INTEGER NOT NULL,
            method   TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

init_db()

def save_draw(numbers: list, max_num: int, method: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO draws (ts, numbers, max_num, method) VALUES (?,?,?,?)",
              (datetime.utcnow().isoformat(), ",".join(map(str, numbers)), max_num, method))
    conn.commit()
    conn.close()

def get_history(limit: int = 20) -> list:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, ts, numbers, max_num, method FROM draws ORDER BY id DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return [{"id": r[0], "ts": r[1], "numbers": list(map(int, r[2].split(","))),
             "max_num": r[3], "method": r[4]} for r in rows]

def get_frequency(max_num: int = 49) -> dict:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT numbers FROM draws WHERE max_num = ?", (max_num,))
    rows = c.fetchall()
    conn.close()
    freq = {i: 0 for i in range(1, max_num + 1)}
    for row in rows:
        for n in map(int, row[0].split(",")):
            if n in freq:
                freq[n] += 1
    return freq


# ─────────────────────────────────────────────
#  Feature 3: Lucky Numbers Analyser
# ─────────────────────────────────────────────

def analyse_lucky_numbers(numbers: list, max_num: int, simulations: int = 500) -> dict:
    """
    Estimate the probability that a given set of numbers appears in a quantum draw
    by running `simulations` quantum lottery draws and counting hits.
    """
    count = len(numbers)
    hits = 0
    for _ in range(simulations):
        draw = quantum_lottery_pick(count=count, max_num=max_num)
        if set(numbers) == set(draw):
            hits += 1

    # Theoretical probability: C(max_num, count) combinations
    from math import comb
    theoretical = 1 / comb(max_num, count)
    empirical = hits / simulations

    return {
        "numbers": numbers,
        "simulations": simulations,
        "hits": hits,
        "empirical_probability": round(empirical, 8),
        "theoretical_probability": round(theoretical, 10),
        "odds_1_in": int(1 / theoretical) if theoretical > 0 else None,
    }


# ─────────────────────────────────────────────
#  Feature 4: Quantum vs Classical Comparison
# ─────────────────────────────────────────────

def shannon_entropy(counts: dict, total: int) -> float:
    """Calculate Shannon entropy (bits) of a distribution."""
    entropy = 0.0
    for c in counts.values():
        if c > 0:
            p = c / total
            entropy -= p * math.log2(p)
    return round(entropy, 4)

def classical_random_pick(count: int, max_num: int) -> list:
    return sorted(random.sample(range(1, max_num + 1), count))

def quantum_vs_classical(count: int = 6, max_num: int = 49, rounds: int = 200) -> dict:
    """
    Run `rounds` draws with both quantum and classical RNG.
    Compare distributions, entropy, and chi-square uniformity.
    """
    n_bits = math.ceil(math.log2(max_num + 1))
    q_freq = {i: 0 for i in range(1, max_num + 1)}
    c_freq = {i: 0 for i in range(1, max_num + 1)}

    for _ in range(rounds):
        q_nums = quantum_lottery_pick(count=count, max_num=max_num)
        c_nums = classical_random_pick(count=count, max_num=max_num)
        for n in q_nums: q_freq[n] += 1
        for n in c_nums: c_freq[n] += 1

    total_q = sum(q_freq.values())
    total_c = sum(c_freq.values())

    q_entropy = shannon_entropy(q_freq, total_q)
    c_entropy = shannon_entropy(c_freq, total_c)

    result = {
        "rounds": rounds,
        "quantum_entropy": q_entropy,
        "classical_entropy": c_entropy,
        "quantum_freq": q_freq,
        "classical_freq": c_freq,
        "quantum_numbers": quantum_lottery_pick(count=count, max_num=max_num),
        "classical_numbers": classical_random_pick(count=count, max_num=max_num),
    }

    if SCIPY_AVAILABLE:
        expected = [total_q / max_num] * max_num
        q_chi2, q_p = chisquare(list(q_freq.values()), f_exp=expected)
        c_chi2, c_p = chisquare(list(c_freq.values()), f_exp=expected)
        result["quantum_chi2"]  = round(float(q_chi2), 4)
        result["quantum_p"]     = round(float(q_p), 4)
        result["classical_chi2"] = round(float(c_chi2), 4)
        result["classical_p"]   = round(float(c_p), 4)

    return result


# ─────────────────────────────────────────────
#  Feature 5: Live Circuit Diagram
# ─────────────────────────────────────────────

def generate_circuit_diagram(n_qubits: int = 6) -> str | None:
    """Render a Hadamard lottery circuit as base64 PNG."""
    if not MATPLOTLIB_AVAILABLE:
        return None
    try:
        qc = QuantumCircuit(n_qubits, n_qubits)
        for i in range(n_qubits):
            qc.h(i)
        qc.barrier()
        qc.measure(range(n_qubits), range(n_qubits))

        buf = io.BytesIO()
        fig = qc.draw(output='mpl', style={'backgroundcolor': '#0d1117',
                                            'textcolor': '#e2e8f0',
                                            'gatetextcolor': '#0d1117',
                                            'subtextcolor': '#64748b'})
        fig.savefig(buf, format='png', bbox_inches='tight',
                    facecolor='#0d1117', dpi=120)
        plt.close(fig)
        buf.seek(0)
        return base64.b64encode(buf.read()).decode('utf-8')
    except Exception:
        return None


# ─────────────────────────────────────────────
#  Feature 6: Entropy Score
# ─────────────────────────────────────────────

def compute_entropy_score(distribution: dict) -> dict:
    """
    Compute Shannon entropy of the quantum state distribution.
    Max entropy for n states = log2(n) bits.
    Score is normalised to 0-100%.
    """
    states = distribution.get("state_distribution", {})
    total  = sum(states.values())
    if total == 0:
        return {"entropy": 0, "max_entropy": 0, "score_pct": 0}

    n_states   = len(states)
    entropy    = shannon_entropy(states, total)
    max_entropy = math.log2(n_states) if n_states > 1 else 1
    score_pct  = round((entropy / max_entropy) * 100, 1) if max_entropy > 0 else 0

    return {
        "entropy": entropy,
        "max_entropy": round(max_entropy, 4),
        "score_pct": score_pct,
        "n_states_observed": n_states,
    }


# ─────────────────────────────────────────────
#  API Routes
# ─────────────────────────────────────────────

@app.route("/api/health", methods=["GET"])
def health():
    """Simple health check endpoint."""
    return jsonify({"status": "ok", "quantum_backend": "qasm_simulator"})


@app.route("/", methods=["GET"])
def index():
    """Serve the frontend page."""
    return send_from_directory(os.path.dirname(__file__), "index.html")


@app.route("/api/lottery", methods=["GET"])
def lottery():
    """
    Main lottery endpoint.
    Query params:
      - count  (int, default 6):  how many numbers to pick
      - max    (int, default 49): upper bound of number range
      - shots  (int, default 512): shots for distribution chart
    """
    try:
        count = int(request.args.get("count", 6))
        max_num = int(request.args.get("max", 49))
        shots = int(request.args.get("shots", 512))

        # Validate inputs
        if not (1 <= count <= 10):
            return jsonify({"error": "count must be between 1 and 10"}), 400
        if not (count < max_num <= 100):
            return jsonify({"error": "max must be > count and ≤ 100"}), 400

        start = time.time()

        numbers = quantum_lottery_pick(count=count, max_num=max_num)
        distribution = quantum_probability_distribution(shots=shots)
        entanglement = quantum_entangled_pair()
        entropy_score = compute_entropy_score(distribution)
        circuit_img   = generate_circuit_diagram(n_qubits=math.ceil(math.log2(max_num + 1)))

        # Save to history DB
        save_draw(numbers, max_num, "quantum")

        elapsed = round(time.time() - start, 3)

        return jsonify({
            "success": True,
            "lottery_numbers": numbers,
            "config": {"count": count, "max_num": max_num},
            "distribution": distribution,
            "entanglement": entanglement,
            "entropy_score": entropy_score,
            "circuit_diagram_b64": circuit_img,
            "generation_time_s": elapsed,
            "method": "Hadamard gate superposition + quantum measurement collapse",
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/single", methods=["GET"])
def single_number():
    """Generate a single quantum random number in a given range."""
    try:
        min_val = int(request.args.get("min", 1))
        max_val = int(request.args.get("max", 100))

        n_bits = math.ceil(math.log2(max_val + 1))
        num = None
        for _ in range(500):
            candidate = quantum_random_int(n_bits)
            if min_val <= candidate <= max_val:
                num = candidate
                break

        if num is None:
            return jsonify({"error": "Failed to generate number in range"}), 500

        return jsonify({"number": num, "range": [min_val, max_val]})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/history", methods=["GET"])
def history():
    """Feature 1 & 2: Return draw history and number frequency heatmap."""
    try:
        max_num = int(request.args.get("max", 49))
        limit   = int(request.args.get("limit", 20))
        draws   = get_history(limit=limit)
        freq    = get_frequency(max_num=max_num)
        return jsonify({"success": True, "draws": draws, "frequency": freq, "max_num": max_num})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/history/clear", methods=["DELETE"])
def clear_history():
    """Clear all draw history."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("DELETE FROM draws")
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/analyse-lucky", methods=["GET"])
def analyse_lucky():
    """Feature 3: Analyse user-supplied lucky numbers."""
    try:
        raw     = request.args.get("numbers", "")
        max_num = int(request.args.get("max", 49))
        sims    = int(request.args.get("simulations", 300))
        numbers = [int(x.strip()) for x in raw.split(",") if x.strip().isdigit()]
        if not numbers:
            return jsonify({"error": "Provide numbers as ?numbers=1,2,3,..."}), 400
        if any(n < 1 or n > max_num for n in numbers):
            return jsonify({"error": f"All numbers must be between 1 and {max_num}"}), 400
        result = analyse_lucky_numbers(numbers, max_num=max_num, simulations=sims)
        return jsonify({"success": True, **result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/compare", methods=["GET"])
def compare():
    """Feature 4: Quantum vs Classical side-by-side comparison."""
    try:
        count   = int(request.args.get("count", 6))
        max_num = int(request.args.get("max", 49))
        rounds  = int(request.args.get("rounds", 100))
        if rounds > 300:
            return jsonify({"error": "rounds max is 300"}), 400
        result = quantum_vs_classical(count=count, max_num=max_num, rounds=rounds)
        return jsonify({"success": True, **result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/circuit-diagram", methods=["GET"])
def circuit_diagram():
    """Feature 5: Return base64 PNG of a quantum lottery circuit."""
    try:
        n_qubits = int(request.args.get("qubits", 6))
        img_b64  = generate_circuit_diagram(n_qubits=min(n_qubits, 10))
        if img_b64 is None:
            return jsonify({"error": "matplotlib not available — pip install matplotlib pylatexenc"}), 500
        return jsonify({"success": True, "image_b64": img_b64, "n_qubits": n_qubits})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


if __name__ == "__main__":
    print("🔬 Quantum Lottery API starting on http://localhost:5000")
    app.run(debug=True, port=5000)
