#!/usr/bin/env python3
"""
Application-Checkpoint-Based Distributed Migration for MPI Jobs

Instead of using CRIU to freeze/restore processes, this migrator leverages
the application's own periodic checkpoints. The flow:

  1. Discover worker pods of an MPIJob
  2. Wait for / locate the latest application checkpoint on rank 0
  3. Extract the checkpoint file from the rank-0 worker pod
  4. Delete the existing MPIJob
  5. Redeploy a new MPIJob on the target nodes with the checkpoint mounted
  6. The application resumes from the checkpoint via its -r (restore) flag

This avoids all CRIU complexity (mount discovery, TCP state, coordinated
dumps) and works with any MPI application that implements its own
checkpoint/resume.
"""

import logging
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import yaml
from kubernetes import client, config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_kubernetes_config():
    try:
        config.load_incluster_config()
    except Exception:
        try:
            config.load_kube_config()
        except Exception as e:
            logger.error(f"Failed to load Kubernetes configuration: {e}")
            return False
    return True


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class WorkerInfo:
    """Tracked state for each discovered MPI worker."""
    pod_name: str
    node_name: str
    rank: int = 0
    container_name: str = "worker"


@dataclass
class DistributedMigrationResult:
    success: bool = False
    job_name: str = ""
    checkpoint_iteration: int = -1
    checkpoint_file: str = ""
    old_workers: List[WorkerInfo] = field(default_factory=list)
    new_job_name: str = ""
    errors: List[str] = field(default_factory=list)
    steps_completed: List[str] = field(default_factory=list)
    elapsed_s: float = 0.0


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def distributed_migrate(
    job_name: str,
    namespace: str,
    target_nodes: List[str],
    mpijob_yaml: Optional[str] = None,
    original_args: Optional[List[str]] = None,
    checkpoint_path_in_pod: Optional[str] = None,
    target_region: Optional[str] = None,
    delete_original: bool = True,
) -> DistributedMigrationResult:
    """
    Migrate an MPI job by redeploying from its latest application checkpoint.

    Args:
        job_name:               Name of the running MPIJob
        namespace:              Kubernetes namespace
        target_nodes:           Target node names for workers (one per worker, rank order)
        mpijob_yaml:            Path to the original MPIJob YAML (auto-fetched if None)
        original_args:          Original launcher args (auto-detected if None)
        checkpoint_path_in_pod: Path to checkpoint dir inside the rank-0 pod
                                (default: /results/)
        target_region:          Optional region label for new pods
        delete_original:        Whether to delete the old MPIJob
    """
    tracker = DistributedMigrationTracker(
        job_name=job_name,
        namespace=namespace,
        target_nodes=target_nodes,
        mpijob_yaml=mpijob_yaml,
        original_args=original_args,
        checkpoint_path_in_pod=checkpoint_path_in_pod or "/results/",
        target_region=target_region,
        delete_original=delete_original,
    )
    return tracker.run()


# ---------------------------------------------------------------------------
# Core tracker
# ---------------------------------------------------------------------------

class DistributedMigrationTracker:
    """Orchestrates application-checkpoint-based migration of MPI jobs."""

    def __init__(
        self,
        job_name: str,
        namespace: str,
        target_nodes: List[str],
        mpijob_yaml: Optional[str] = None,
        original_args: Optional[List[str]] = None,
        checkpoint_path_in_pod: str = "/results/",
        target_region: Optional[str] = None,
        delete_original: bool = True,
    ):
        self.job_name = job_name
        self.namespace = namespace
        self.target_nodes = target_nodes
        self.mpijob_yaml = mpijob_yaml
        self.original_args = original_args
        self.checkpoint_path_in_pod = checkpoint_path_in_pod
        self.target_region = target_region
        self.delete_original = delete_original

        self.workers: List[WorkerInfo] = []
        self.launcher_pod: Optional[str] = None
        self.launcher_args: List[str] = []
        self.image: str = ""
        self.num_workers: int = 0
        self.checkpoint_local_path: str = ""
        self.checkpoint_iteration: int = -1
        self.new_job_name: str = ""
        self.original_mpijob_spec: Optional[Dict] = None

        self.result = DistributedMigrationResult(job_name=job_name)
        self.start_time = time.time()

    # ------------------------------------------------------------------
    # Orchestration
    # ------------------------------------------------------------------

    def run(self) -> DistributedMigrationResult:
        try:
            logger.info("=" * 80)
            logger.info(f"[DIST_MIGRATE] Starting checkpoint-based migration for {self.job_name}")
            logger.info("=" * 80)

            self._step("discover_workers")
            self._discover_workers()

            self._step("extract_job_spec")
            self._extract_job_spec()

            self._step("locate_checkpoint")
            self._locate_checkpoint()

            self._step("extract_checkpoint")
            self._extract_checkpoint()

            if self.delete_original:
                self._step("delete_old_job")
                self._delete_old_job()

            self._step("deploy_new_job")
            self._deploy_new_job()

            self._step("verify")
            self._verify_new_job()

            self.result.success = True

        except Exception as e:
            logger.error(f"[DIST_MIGRATE] Migration failed: {e}")
            self.result.errors.append(str(e))
        finally:
            self.result.elapsed_s = time.time() - self.start_time
            self.result.old_workers = self.workers
            self.result.checkpoint_iteration = self.checkpoint_iteration
            self.result.new_job_name = self.new_job_name
            self._log_summary()

        return self.result

    def _step(self, name: str):
        logger.info(f"[DIST_MIGRATE] === Step: {name} ===")
        self.result.steps_completed.append(f"{time.time()}: {name}")

    # ------------------------------------------------------------------
    # 1. Discover workers
    # ------------------------------------------------------------------

    def _discover_workers(self):
        """Find all worker and launcher pods for this MPIJob."""
        load_kubernetes_config()
        api = client.CoreV1Api()

        # Find workers via Kubeflow labels
        pods = api.list_namespaced_pod(
            namespace=self.namespace,
            label_selector=f"training.kubeflow.org/job-name={self.job_name}",
        )

        for pod in sorted(pods.items, key=lambda p: p.metadata.name):
            labels = pod.metadata.labels or {}
            role = labels.get("training.kubeflow.org/job-role", "")

            if role == "worker":
                # Determine rank from pod name (e.g. nbody-sim-worker-0 -> rank 0)
                rank = 0
                match = re.search(r"-(\d+)$", pod.metadata.name)
                if match:
                    rank = int(match.group(1))

                w = WorkerInfo(
                    pod_name=pod.metadata.name,
                    node_name=pod.spec.node_name or "",
                    rank=rank,
                    container_name=pod.spec.containers[0].name if pod.spec.containers else "worker",
                )
                self.workers.append(w)
                logger.info(f"[DISCOVER] Worker rank {rank}: {w.pod_name} on {w.node_name}")

            elif role == "launcher":
                self.launcher_pod = pod.metadata.name
                logger.info(f"[DISCOVER] Launcher: {pod.metadata.name}")

        if not self.workers:
            # Fallback: match by name prefix
            all_pods = api.list_namespaced_pod(namespace=self.namespace)
            for pod in sorted(all_pods.items, key=lambda p: p.metadata.name):
                if pod.metadata.name.startswith(f"{self.job_name}-worker-"):
                    rank = 0
                    match = re.search(r"-(\d+)$", pod.metadata.name)
                    if match:
                        rank = int(match.group(1))
                    self.workers.append(WorkerInfo(
                        pod_name=pod.metadata.name,
                        node_name=pod.spec.node_name or "",
                        rank=rank,
                    ))

        self.workers.sort(key=lambda w: w.rank)
        self.num_workers = len(self.workers)

        if not self.workers:
            raise RuntimeError(f"No worker pods found for job {self.job_name}")

        if len(self.target_nodes) < self.num_workers:
            raise ValueError(
                f"Need {self.num_workers} target nodes but only got {len(self.target_nodes)}"
            )

        logger.info(f"[DISCOVER] Found {self.num_workers} workers")

    # ------------------------------------------------------------------
    # 2. Extract existing job spec
    # ------------------------------------------------------------------

    def _extract_job_spec(self):
        """
        Get the original MPIJob spec so we can redeploy with modifications.
        Either from a provided YAML or by fetching the live resource.
        """
        if self.mpijob_yaml and os.path.isfile(self.mpijob_yaml):
            with open(self.mpijob_yaml) as f:
                self.original_mpijob_spec = yaml.safe_load(f)
            logger.info(f"[JOB_SPEC] Loaded MPIJob spec from {self.mpijob_yaml}")
        else:
            # Fetch the live MPIJob resource via kubectl
            logger.info("[JOB_SPEC] Fetching live MPIJob spec via kubectl")
            r = subprocess.run(
                f"kubectl get mpijob {self.job_name} -n {self.namespace} -o yaml",
                shell=True, capture_output=True, text=True, timeout=15,
            )
            if r.returncode != 0:
                raise RuntimeError(f"Failed to get MPIJob spec: {r.stderr}")
            self.original_mpijob_spec = yaml.safe_load(r.stdout)

        # Extract launcher args and image
        launcher_spec = (
            self.original_mpijob_spec
            .get("spec", {})
            .get("mpiReplicaSpecs", {})
            .get("Launcher", {})
            .get("template", {})
            .get("spec", {})
            .get("containers", [{}])[0]
        )
        self.launcher_args = self.original_args or launcher_spec.get("command", [])
        self.image = launcher_spec.get("image", "")

        # Extract worker image if different
        worker_spec = (
            self.original_mpijob_spec
            .get("spec", {})
            .get("mpiReplicaSpecs", {})
            .get("Worker", {})
            .get("template", {})
            .get("spec", {})
            .get("containers", [{}])[0]
        )
        if not self.image:
            self.image = worker_spec.get("image", "")

        logger.info(f"[JOB_SPEC] Image: {self.image}")
        logger.info(f"[JOB_SPEC] Launcher command: {self.launcher_args}")

    # ------------------------------------------------------------------
    # 3. Locate checkpoint
    # ------------------------------------------------------------------

    def _locate_checkpoint(self):
        """
        Find the latest checkpoint file on the rank-0 worker.

        The nbody sim writes checkpoints to:
          {results_folder}/{total_bodies}/checkpoint.dat

        The checkpoint.dat is binary: [int: iteration][body data...]
        """
        rank0 = self._get_rank0()

        # List the results directory to find checkpoint files
        cmd = (
            f"kubectl exec -n {self.namespace} {rank0.pod_name} "
            f"-c {rank0.container_name} -- "
            f"find {self.checkpoint_path_in_pod} -name 'checkpoint.dat' -type f"
        )
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)

        if r.returncode != 0 or not r.stdout.strip():
            raise RuntimeError(
                f"No checkpoint.dat found in {self.checkpoint_path_in_pod} on {rank0.pod_name}. "
                f"The application may not have written a checkpoint yet. "
                f"stderr: {r.stderr.strip()}"
            )

        # Take the first (or most recent) checkpoint file
        checkpoint_files = r.stdout.strip().split("\n")
        self.result.checkpoint_file = checkpoint_files[0]
        logger.info(f"[CHECKPOINT] Found: {self.result.checkpoint_file}")

        # Read the iteration number from the checkpoint (first 4 bytes = int)
        cmd = (
            f"kubectl exec -n {self.namespace} {rank0.pod_name} "
            f"-c {rank0.container_name} -- "
            f"python3 -c \"import struct; f=open('{self.result.checkpoint_file}','rb'); "
            f"print(struct.unpack('i', f.read(4))[0])\""
        )
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)

        if r.returncode == 0 and r.stdout.strip():
            try:
                self.checkpoint_iteration = int(r.stdout.strip())
                logger.info(f"[CHECKPOINT] Checkpoint is at iteration {self.checkpoint_iteration}")
            except ValueError:
                logger.warning(f"[CHECKPOINT] Could not parse iteration: {r.stdout.strip()}")
        else:
            logger.warning("[CHECKPOINT] Could not read iteration number from checkpoint")

    # ------------------------------------------------------------------
    # 4. Extract checkpoint from pod
    # ------------------------------------------------------------------

    def _extract_checkpoint(self):
        """Copy checkpoint.dat from the rank-0 pod to a local temp file."""
        rank0 = self._get_rank0()
        remote_path = self.result.checkpoint_file

        # Create a temp directory that persists until we deploy the new job
        tmpdir = tempfile.mkdtemp(prefix="kubeflex_ckpt_")
        local_path = os.path.join(tmpdir, "checkpoint.dat")

        cmd = (
            f"kubectl cp {self.namespace}/{rank0.pod_name}:{remote_path} "
            f"{local_path} -c {rank0.container_name}"
        )
        logger.info(f"[EXTRACT] Copying checkpoint: {cmd}")
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)

        if r.returncode != 0:
            raise RuntimeError(f"Failed to extract checkpoint: {r.stderr}")

        size = os.path.getsize(local_path)
        logger.info(f"[EXTRACT] Checkpoint saved to {local_path} ({size} bytes)")
        self.checkpoint_local_path = local_path

        # Also copy progress.csv if it exists (for metrics)
        progress_dir = os.path.dirname(remote_path)
        progress_remote = os.path.join(progress_dir, "progress.csv")
        progress_local = os.path.join(tmpdir, "progress.csv")
        subprocess.run(
            f"kubectl cp {self.namespace}/{rank0.pod_name}:{progress_remote} "
            f"{progress_local} -c {rank0.container_name}",
            shell=True, capture_output=True, text=True, timeout=30,
        )

    # ------------------------------------------------------------------
    # 5. Delete old job
    # ------------------------------------------------------------------

    def _delete_old_job(self):
        """Delete the existing MPIJob and wait for pods to terminate."""
        logger.info(f"[DELETE] Deleting MPIJob {self.job_name}")

        r = subprocess.run(
            f"kubectl delete mpijob {self.job_name} -n {self.namespace} --grace-period=10",
            shell=True, capture_output=True, text=True, timeout=60,
        )
        if r.returncode != 0:
            logger.warning(f"[DELETE] kubectl delete mpijob: {r.stderr}")

        # Wait for worker pods to be gone
        logger.info("[DELETE] Waiting for old pods to terminate...")
        for attempt in range(30):
            r = subprocess.run(
                f"kubectl get pods -n {self.namespace} "
                f"-l training.kubeflow.org/job-name={self.job_name} "
                f"--no-headers 2>/dev/null | wc -l",
                shell=True, capture_output=True, text=True, timeout=10,
            )
            count = int(r.stdout.strip()) if r.stdout.strip().isdigit() else 0
            if count == 0:
                break
            time.sleep(2)

        logger.info("[DELETE] Old job deleted")

    # ------------------------------------------------------------------
    # 6. Deploy new job
    # ------------------------------------------------------------------

    def _deploy_new_job(self):
        """
        Deploy a new MPIJob that resumes from the extracted checkpoint.

        Changes from the original spec:
          - Job name gets a migration counter suffix
          - Launcher command gets -r (restore) flag added
          - Checkpoint file is uploaded to the rank-0 worker via an init
            mechanism (ConfigMap or kubectl cp after pod starts)
          - Worker nodeSelector set to target nodes
        """
        spec = self._deep_copy_spec()

        # Generate new job name
        self.new_job_name = self._next_job_name()
        spec["metadata"]["name"] = self.new_job_name
        spec["metadata"]["namespace"] = self.namespace

        # Clean up fields that shouldn't be carried over from a live resource
        metadata = spec.get("metadata", {})
        for key in ["resourceVersion", "uid", "creationTimestamp", "generation",
                     "managedFields", "selfLink"]:
            metadata.pop(key, None)
        spec.get("spec", {}).get("runPolicy", {}).pop("startTime", None)
        status = spec.pop("status", None)

        # Modify launcher command to add -r (restore) flag
        launcher_containers = (
            spec["spec"]["mpiReplicaSpecs"]["Launcher"]["template"]["spec"]["containers"]
        )
        for container in launcher_containers:
            cmd = container.get("command", [])
            if cmd and "-r" not in cmd:
                container["command"] = cmd + ["-r"]
                logger.info(f"[DEPLOY] Added -r flag. New command: {container['command']}")

        # Add node affinity to workers for target placement
        worker_template = spec["spec"]["mpiReplicaSpecs"]["Worker"]["template"]["spec"]

        # We can't pin individual ranks to specific nodes with a single
        # Worker replica spec (all replicas share the same spec). Instead,
        # we use a node affinity that allows scheduling on any of the target nodes.
        target_node_set = list(set(self.target_nodes[:self.num_workers]))
        worker_template["affinity"] = {
            "nodeAffinity": {
                "requiredDuringSchedulingIgnoredDuringExecution": {
                    "nodeSelectorTerms": [{
                        "matchExpressions": [{
                            "key": "kubernetes.io/hostname",
                            "operator": "In",
                            "values": target_node_set,
                        }]
                    }]
                }
            }
        }

        # Add migration annotations
        if "annotations" not in spec.get("metadata", {}):
            spec["metadata"]["annotations"] = {}
        spec["metadata"]["annotations"].update({
            "kubeflex.io/migrated-from": self.job_name,
            "kubeflex.io/checkpoint-iteration": str(self.checkpoint_iteration),
            "kubeflex.io/migration-timestamp": str(int(time.time())),
            "kubeflex.io/migration-method": "application-checkpoint",
        })

        if self.target_region:
            spec["metadata"]["annotations"]["kubeflex.io/target-region"] = self.target_region

        # Write the new spec to a temp file and apply
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, prefix="kubeflex_mpijob_"
        ) as f:
            yaml.dump(spec, f, default_flow_style=False)
            spec_path = f.name

        logger.info(f"[DEPLOY] Applying new MPIJob {self.new_job_name} from {spec_path}")

        try:
            r = subprocess.run(
                f"kubectl apply -f {spec_path}",
                shell=True, capture_output=True, text=True, timeout=30,
            )
            if r.returncode != 0:
                raise RuntimeError(f"Failed to apply new MPIJob: {r.stderr}")
            logger.info(f"[DEPLOY] MPIJob {self.new_job_name} created")
        finally:
            os.unlink(spec_path)

        # Wait for new worker pods to appear and become Running
        self._wait_for_new_workers()

        # Upload checkpoint file to the rank-0 worker pod
        self._upload_checkpoint_to_rank0()

    def _wait_for_new_workers(self):
        """Wait for the new MPIJob's worker pods to be Running."""
        logger.info("[DEPLOY] Waiting for new worker pods...")

        for attempt in range(60):
            r = subprocess.run(
                f"kubectl get pods -n {self.namespace} "
                f"-l training.kubeflow.org/job-name={self.new_job_name},"
                f"training.kubeflow.org/job-role=worker "
                f"-o jsonpath='{{range .items[*]}}{{.metadata.name}} {{.status.phase}}{{\"\\n\"}}{{end}}'",
                shell=True, capture_output=True, text=True, timeout=10,
            )

            lines = [l for l in r.stdout.strip().split("\n") if l.strip()]
            running = [l for l in lines if "Running" in l]

            if len(running) >= self.num_workers:
                for l in running:
                    logger.info(f"[DEPLOY] {l}")
                return

            time.sleep(2)

        raise RuntimeError(
            f"New worker pods did not reach Running state within 120s"
        )

    def _upload_checkpoint_to_rank0(self):
        """
        Copy the checkpoint file into the new rank-0 worker pod.

        The checkpoint goes to the same path the application expects:
          {checkpoint_path_in_pod}/{bodies}/checkpoint.dat
        """
        # Find the new rank-0 pod
        r = subprocess.run(
            f"kubectl get pods -n {self.namespace} "
            f"-l training.kubeflow.org/job-name={self.new_job_name},"
            f"training.kubeflow.org/job-role=worker "
            f"-o jsonpath='{{range .items[*]}}{{.metadata.name}}{{\"\\n\"}}{{end}}'",
            shell=True, capture_output=True, text=True, timeout=10,
        )
        new_workers = sorted(r.stdout.strip().split("\n"))
        if not new_workers:
            raise RuntimeError("No new worker pods found for checkpoint upload")

        new_rank0 = new_workers[0]
        remote_dir = os.path.dirname(self.result.checkpoint_file)

        # Create the directory in the new pod
        subprocess.run(
            f"kubectl exec -n {self.namespace} {new_rank0} -c worker -- mkdir -p {remote_dir}",
            shell=True, capture_output=True, text=True, timeout=15,
        )

        # Copy checkpoint
        cmd = (
            f"kubectl cp {self.checkpoint_local_path} "
            f"{self.namespace}/{new_rank0}:{self.result.checkpoint_file} "
            f"-c worker"
        )
        logger.info(f"[UPLOAD] {cmd}")
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise RuntimeError(f"Failed to upload checkpoint to {new_rank0}: {r.stderr}")

        logger.info(f"[UPLOAD] Checkpoint uploaded to {new_rank0}:{self.result.checkpoint_file}")

        # Also upload progress.csv if we have it
        progress_local = os.path.join(os.path.dirname(self.checkpoint_local_path), "progress.csv")
        if os.path.isfile(progress_local):
            progress_remote = os.path.join(remote_dir, "progress.csv")
            subprocess.run(
                f"kubectl cp {progress_local} {self.namespace}/{new_rank0}:{progress_remote} -c worker",
                shell=True, capture_output=True, text=True, timeout=30,
            )

    # ------------------------------------------------------------------
    # 7. Verify
    # ------------------------------------------------------------------

    def _verify_new_job(self):
        """Check that the new job is running and the launcher has started."""
        # Check for launcher pod
        for attempt in range(30):
            r = subprocess.run(
                f"kubectl get pods -n {self.namespace} "
                f"-l training.kubeflow.org/job-name={self.new_job_name},"
                f"training.kubeflow.org/job-role=launcher "
                f"-o jsonpath='{{.items[0].status.phase}}'",
                shell=True, capture_output=True, text=True, timeout=10,
            )
            phase = r.stdout.strip()
            if phase in ("Running", "Succeeded"):
                logger.info(f"[VERIFY] Launcher phase: {phase}")
                break
            time.sleep(2)
        else:
            self.result.errors.append("Launcher did not reach Running state")
            logger.warning("[VERIFY] Launcher not Running yet (may still be starting)")

        # Check all workers are still Running
        r = subprocess.run(
            f"kubectl get pods -n {self.namespace} "
            f"-l training.kubeflow.org/job-name={self.new_job_name},"
            f"training.kubeflow.org/job-role=worker "
            f"-o jsonpath='{{range .items[*]}}{{.metadata.name}} {{.status.phase}}{{\"\\n\"}}{{end}}'",
            shell=True, capture_output=True, text=True, timeout=10,
        )
        for line in r.stdout.strip().split("\n"):
            if line.strip():
                logger.info(f"[VERIFY] {line}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_rank0(self) -> WorkerInfo:
        """Get the rank-0 worker."""
        for w in self.workers:
            if w.rank == 0:
                return w
        # Fallback: first worker by name
        return self.workers[0]

    def _deep_copy_spec(self) -> Dict:
        """Deep copy the MPIJob spec via YAML round-trip."""
        return yaml.safe_load(yaml.dump(self.original_mpijob_spec))

    def _next_job_name(self) -> str:
        """Generate the next job name with a migration counter."""
        base = re.sub(r"-mig-\d+$", "", self.job_name)

        load_kubernetes_config()
        # List existing mpijobs to find the highest migration counter
        r = subprocess.run(
            f"kubectl get mpijobs -n {self.namespace} -o jsonpath='{{range .items[*]}}{{.metadata.name}}{{\"\\n\"}}{{end}}'",
            shell=True, capture_output=True, text=True, timeout=10,
        )
        existing = r.stdout.strip().split("\n") if r.stdout.strip() else []

        max_counter = 0
        for name in existing:
            match = re.search(rf"^{re.escape(base)}-mig-(\d+)$", name)
            if match:
                max_counter = max(max_counter, int(match.group(1)))

        new_name = f"{base}-mig-{max_counter + 1}"
        logger.info(f"[NAMING] New job name: {new_name}")
        return new_name

    def _log_summary(self):
        logger.info("=" * 80)
        logger.info("[DIST_MIGRATE] Migration Summary:")
        logger.info(f"  Old job:    {self.job_name}")
        logger.info(f"  New job:    {self.new_job_name}")
        logger.info(f"  Method:     application-checkpoint")
        logger.info(f"  Checkpoint: iteration {self.checkpoint_iteration}")
        logger.info(f"  Workers:    {self.num_workers}")
        logger.info(f"  Targets:    {self.target_nodes[:self.num_workers]}")
        logger.info(f"  Success:    {self.result.success}")
        logger.info(f"  Elapsed:    {self.result.elapsed_s:.1f}s")
        if self.result.errors:
            logger.info(f"  Errors:     {self.result.errors}")
        logger.info("=" * 80)
