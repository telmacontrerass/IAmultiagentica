# RUDIGER AI Workstation — Usage & Environment Guide

*Last updated: **2026-02-17***

---

## 1) Hardware & OS

* **Host:** `RUDIGER`
* **OS:** Ubuntu **22.04.5 LTS** (“jammy”)
* **Kernel:** `6.8.0-78-generic` (HWE)
* **Hostname:** RUDIGER

**CPU**

* Model: AMD **Ryzen Threadripper PRO 7975WX** (32 cores, 64 threads)
* Sockets/Cores/Threads: 1 / 32 / 64
* Frequency limits: **545 MHz – 5.35 GHz**
* Caches: L1d 1 MiB, L1i 1 MiB, L2 32 MiB, L3 **128 MiB**
* NUMA: **1 node** (node0 CPUs 0–63, size 128 GiB)

**GPUs**

* 2 × **NVIDIA RTX A6000**

  * GPU0 (Display=On) — \~417 MiB used (desktop processes)
  * GPU1 (Display=Off) — \~15 MiB used
  * VRAM: \~49 GiB + \~46 GiB available
* **Topology:** `NODE` between GPUs (no NVLink); CPU affinity 0-63; NUMA affinity 0

**Disk:** 1 TB

---

## 2) Microcode & Kernel Extras

* **AMD microcode:** `amd64-microcode 3.20191218.1ubuntu2.3`
* **HWE meta:** `linux-generic-hwe-22.04` → **6.8.0-78.78\~22.04.1**

---

## 3) CPU Frequency Driver & Governor

* **Scaling driver:** `amd-pstate-epp`
* **Available governors:** `performance`, `powersave`
* **Current policy:** `performance` (545 MHz – 5.35 GHz)
* **Kernel cmdline:** `quiet splash vt.handoff=7`

> Note: `cpupower` oneshot services show as *inactive* after running — that’s normal.

---

## 4) NVIDIA Driver & CUDA

* **Driver:** NVIDIA **575.64.03**
* **CUDA (driver compatibility):** **12.9**
* **System-level CUDA/cuDNN via APT:** **Not installed**

  * Instead, CUDA/cuDNN are provided inside the conda/pip environments.

---

## 5) Shared Conda Environments (Read-Only)

Base Conda: **Miniforge** at `/opt/miniforge3`

| Env name         | Path                                  | Purpose                            |
| ---------------- | ------------------------------------- | ---------------------------------- |
| `pytorch-env`    | `/opt/miniforge3/envs/pytorch-env`    | PyTorch (CUDA 12.4 build)          |
| `tensorflow-env` | `/opt/miniforge3/envs/tensorflow-env` | TensorFlow 2.20 (CUDA 12.x wheels) |

### 5.1 Key Packages

#### `pytorch-env`

* **Python:** 3.10.14
* **PyTorch:** 2.5.1 (`py3.10_cuda12.4_cudnn9.1.0_0`)
* **TorchVision / Torchaudio:** 0.20.1 / 2.5.1 (both cu124)
* **CUDA libs:** `cuda-cudart 12.4.127`, `cuda-nvrtc 12.4.127`, `libcublas 12.4.5.8`, `libcufft 11.2.1.3`, `libcusolver 11.6.1.9`, `libcusparse 12.3.1.170`, `libnpp 12.2.5.30`, `libnvjitlink 12.4.127`, `libnvfatbin 12.9.82`
* **Math/BLAS:** MKL 2022.1
* **NumPy:** 2.2.6
* **cuDNN:** 9.1 (bundled with PyTorch build)

#### `tensorflow-env`

* **Python:** 3.10.18
* **TensorFlow:** 2.20.0 (pip)
* **Keras:** 3.11.3
* **NumPy / h5py:** 2.2.6 / 3.14.0
* **NVIDIA CUDA/cuDNN wheels:** `nvidia-cuda-runtime-cu12 12.9.79`, `nvidia-cublas-cu12 12.9.1.4`, `nvidia-cufft-cu12 11.4.1.4`, `nvidia-cusolver-cu12 11.7.5.82`, `nvidia-cusparse-cu12 12.5.10.65`, `nvidia-curand-cu12 10.3.10.19`, `nvidia-nccl-cu12 2.27.7`, `nvidia-cudnn-cu12 9.12.0.46`, `nvidia-nvjitlink-cu12 12.9.86`, `nvidia-cuda-nvcc-cu12 12.9.86`
* **Note:** This env includes **NVCC toolchain** for compiling custom ops.

---

## 6) Getting Started

### SSH in

```bash
ssh <your_user>@130.206.73.18
```

### Activate an environment

```bash
conda activate pytorch-env     # or tensorflow-env
```

### Keep jobs running

```bash
tmux new -s train
# run training here
Ctrl-b d   # detach
tmux attach -t train
```

### Run Jupyter Lab

On server:

```bash
conda activate pytorch-env
jupyter lab --no-browser --port 8888
```

On local machine:

```bash
ssh -N -L 8888:localhost:8888 <your_user>@<host_or_ip>
```

→ Open [http://localhost:8888](http://localhost:8888)

---

## 7) GPU Smoke Tests

### PyTorch

```bash
conda activate pytorch-env
python - <<'PY'
import torch
print("PyTorch:", torch.__version__)
print("CUDA available:", torch.cuda.is_available())
if torch.cuda.is_available():
    print("CUDA build:", torch.version.cuda)
    print("cuDNN:", torch.backends.cudnn.version())
    print("GPU 0:", torch.cuda.get_device_name(0))
PY
```

### TensorFlow

```bash
conda activate tensorflow-env
python - <<'PY'
import tensorflow as tf
print("TF:", tf.__version__)
print("GPUs:", tf.config.list_physical_devices('GPU'))
try:
    from tensorflow.python.platform import build_info as tfbuild
    print("Build info keys:", list(tfbuild.build_info.keys()))
except Exception as e:
    print("Build info not available:", e)
PY
```

---

## 8) Custom Envs

Since shared envs are read-only:

**Clone and customize**

```bash
conda create -y -n mytorch --clone /opt/miniforge3/envs/pytorch-env
```

**Or create fresh**

```bash
conda create -y -n myenv python=3.10
conda activate myenv
conda config --add channels conda-forge
conda config --set channel_priority strict
```

---

## 9) Reproducibility

```bash
# Export shared envs
conda list -n /opt/miniforge3/envs/pytorch-env > ~/pytorch-env-freeze.txt
conda list -n /opt/miniforge3/envs/tensorflow-env > ~/tensorflow-env-freeze.txt

# Export your env
conda env export -n myenv > myenv.yml
```

---

## 10) Docker Usage

Docker is installed with the **NVIDIA Container Toolkit**. The default runtime is already set to `nvidia`, so GPU containers “just work.”

### 10.1 Basic sanity

```bash
docker run --rm hello-world
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

### 10.2 Run a PyTorch GPU container

```bash
docker run --rm --gpus all python:3.10 bash -lc '
pip install torch==2.5.1+cu124 torchvision --index-url https://download.pytorch.org/whl/cu124 >/dev/null
python - <<PY
import torch
print("Torch:", torch.__version__)
print("CUDA available:", torch.cuda.is_available())
if torch.cuda.is_available():
    print("Device count:", torch.cuda.device_count())
    print("GPU 0:", torch.cuda.get_device_name(0))
PY
'
```

### 10.3 Run a TensorFlow GPU container

```bash
 docker run --rm --gpus all nvcr.io/nvidia/tensorflow:24.04-tf2-py3 bash -lc '
python - <<PY
import tensorflow as tf
print("TF:", tf.__version__)
print("GPUs:", tf.config.list_physical_devices("GPU"))
PY
'
```

### 10.4 NGC (NVIDIA GPU Cloud) containers

For fully supported builds from NVIDIA:

```bash
docker run --rm --gpus all nvcr.io/nvidia/tensorflow:24.04-tf2-py3 nvidia-smi
```

> **Tip:** For heavy training, add flags as recommended by NVIDIA:
>
> ```bash
> docker run --gpus all --ipc=host --ulimit memlock=-1 --ulimit stack=67108864 ...
> ```

---

## 11) Etiquette & Best Practices

* Use one GPU per job unless multi-GPU aware.
* Free GPUs when done.
* Use `tmux` for long jobs.
* Pin dependencies (`requirements.txt` / `environment.yml`).
* Keep datasets in shared locations.

---

## 12) Remote Access with VS Code

This server is prepared for **VS Code Remote-SSH**.

1. Install VS Code + *Remote-SSH* extension.
2. Connect: **Remote-SSH: Connect to Host…** → `<your_user>@<host_or_ip>`
3. Select a remote folder.
4. In the integrated terminal:

   ```bash
   conda activate pytorch-env
   ```
5. Select Python interpreter:
   `/opt/miniforge3/envs/pytorch-env/bin/python`

---