#!/usr/bin/env python3
"""
Kubernetes Pod Migration Service using CRIU

This service provides a REST API for pod migration using CRIU-based
checkpoint and restore functionality.
"""

import logging
import time
import sys
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from kubernetes import client, config
import uvicorn

# Import the migration functions - adjust path to find migrator module
sys.path.insert(0, str(Path(__file__).parent.parent))
from migrator.live_migration import criu_migrate_pod, load_kubernetes_config

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
)
logger = logging.getLogger(__name__)

# FastAPI app
app = FastAPI(title="Flex-Nautilus Migration Service", version="3.0.0")

# Define input model
class MigrateRequest(BaseModel):
    namespace: str
    pod: str
    source_node: str
    target_node: str
    target_pod: Optional[str] = None
    target_region: Optional[str] = None  # Region of the target node (for node selection, not naming)
    delete_original: bool = True
    debug: bool = True

@app.get("/")
async def root():
    """Root endpoint for service health check."""
    return {
        "message": "Flex-Nautilus Migration Service v3.0.0", 
        "status": "running",
        "version": "3.0.0"
    }

@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy", 
        "service": "migration-service",
        "version": "3.0.0",
        "description": "Kubernetes pod migration service with CRIU-based migration"
    }

@app.get("/info")
async def info():
    """Service information endpoint."""
    return {
        "service": "Flex-Nautilus Migration Service",
        "version": "3.0.0",
        "description": "Kubernetes pod migration service with CRIU-based migration",
        "endpoints": {
            "migrate": "POST /live-migrate - CRIU-based migration with checkpointing",
            "health": "GET /health - Health check",
            "info": "GET /info - Service information",
            "nodes": "GET /nodes - List nodes",
            "pods": "GET /pods/{namespace} - List pods in a namespace",
            "migration-status": "GET /migration-status/{pod_name} - Get migration status for a pod"
        }
    }


@app.post("/live-migrate")
async def live_migrate(req: MigrateRequest):
    """
    Perform CRIU-based migration with checkpointing.
    
    This endpoint uses CRIU (Checkpoint/Restore in Userspace) to perform migration
    of pods between KIND nodes. It creates a checkpoint of the source container
    and restores it on the target node.
    
    Args:
        req: Migration request containing pod details and target node
        
    Returns:
        dict: Migration result with detailed status, checkpoint path, and migration details
    """
    try:
        logger.info(f"[API] Received migration request for pod {req.pod} to node {req.target_node}")
        logger.info(f"[API] Namespace: {req.namespace}, Target pod: {req.target_pod}")
        logger.info(f"[API] Target region: {req.target_region}, Delete original: {req.delete_original}, Debug: {req.debug}")
        
        # If target_region not provided or empty, try to get it from the target node
        # (This is for node selection purposes, not for naming)
        if not req.target_region or (isinstance(req.target_region, str) and not req.target_region.strip()):
            try:
                load_kubernetes_config()
                api = client.CoreV1Api()
                node = api.read_node(name=req.target_node)
                req.target_region = node.metadata.labels.get("REGION") if node.metadata.labels else None
                if req.target_region:
                    logger.info(f"[API] Determined target region from node labels: {req.target_region}")
                else:
                    logger.warning(f"[API] Could not determine target region from node {req.target_node} (labels: {node.metadata.labels})")
            except Exception as e:
                logger.warning(f"[API] Failed to get target region from node: {e}")
                import traceback
                logger.warning(f"[API] Traceback: {traceback.format_exc()}")
        
        # Perform migration using the simplified criu_migrate_pod function
        # Note: target_region is passed but not used for naming (counter-based naming is used instead)
        migration_result = criu_migrate_pod(
            source_pod=req.pod,
            source_node=req.source_node,
            target_node=req.target_node,
            namespace=req.namespace,
            target_region=req.target_region,
            delete_original=req.delete_original,
            checkpoint_dir=f"/tmp/checkpoints"
        )
        
        # Extract success status and create checkpoint path
        success = migration_result.get("success", False)
        checkpoint_path = f"/tmp/checkpoints/migration_{req.pod}.json"
        
        if success:
            logger.info(f"[API] Migration successful. Checkpoint: {checkpoint_path}")
            return {
                "status": "success",
                "checkpoint_path": checkpoint_path,
                "message": f"Successfully performed migration of pod {req.pod}",
                "migration_details": migration_result
            }
        else:
            logger.error("[API] Migration failed - no checkpoint created")
            raise HTTPException(
                status_code=500,
                detail=f"Migration failed: {migration_result.get('error', 'Unknown error')}"
            )
            
    except Exception as e:
        logger.exception("[API] Exception during migration")
        raise HTTPException(
            status_code=500,
            detail=f"Migration failed: {str(e)}"
        )

@app.get("/nodes")
async def list_nodes():
    """List all nodes in the cluster."""
    try:
        load_kubernetes_config()
        api = client.CoreV1Api()
        nodes = api.list_node()
        
        node_list = []
        for node in nodes.items:
            node_info = {
                "name": node.metadata.name,
                "labels": node.metadata.labels or {},
                "annotations": node.metadata.annotations or {},
                "taints": []
            }
            
            # Extract taints
            if node.spec.taints:
                node_info["taints"] = [{
                    "key": taint.key,
                    "value": taint.value,
                    "effect": taint.effect
                } for taint in node.spec.taints]
            
            node_list.append(node_info)
        
        return {
            "status": "success",
            "nodes": node_list,
            "count": len(node_list)
        }
        
    except Exception as e:
        logger.exception("[API] Exception listing nodes")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list nodes: {str(e)}"
        )

@app.get("/migration-status/{pod_name}")
async def get_migration_status(pod_name: str, namespace: str = "default"):
    """Get migration status for a specific pod."""
    try:
        load_kubernetes_config()
        api = client.CoreV1Api()
        
        # Get pod information
        pod = api.read_namespaced_pod(name=pod_name, namespace=namespace)
        
        # Check if pod has migration annotations
        annotations = pod.metadata.annotations or {}
        migration_status = {
            "pod_name": pod_name,
            "namespace": namespace,
            "current_node": pod.spec.node_name,
            "phase": pod.status.phase,
            "migrated": annotations.get("migrated", "false") == "true",
            "migration_timestamp": annotations.get("migration-timestamp"),
            "source_node": annotations.get("source-node"),
            "target_node": annotations.get("target-node"),
            "migration_method": annotations.get("migration-method", "unknown")
        }
        
        return {
            "status": "success",
            "migration_status": migration_status
        }
        
    except Exception as e:
        logger.exception(f"[API] Exception getting migration status for pod {pod_name}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get migration status for pod {pod_name}: {str(e)}"
        )

@app.get("/pods/{namespace}")
async def list_pods(namespace: str):
    """List all pods in a specific namespace."""
    try:
        load_kubernetes_config()
        api = client.CoreV1Api()
        pods = api.list_namespaced_pod(namespace=namespace)
        
        pod_list = []
        for pod in pods.items:
            pod_info = {
                "name": pod.metadata.name,
                "namespace": pod.metadata.namespace,
                "node": pod.spec.node_name,
                "phase": pod.status.phase,
                "labels": pod.metadata.labels or {},
                "annotations": pod.metadata.annotations or {}
            }
            pod_list.append(pod_info)
        
        return {
            "status": "success",
            "namespace": namespace,
            "pods": pod_list,
            "count": len(pod_list)
        }
        
    except Exception as e:
        logger.exception(f"[API] Exception listing pods in namespace {namespace}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list pods in namespace {namespace}: {str(e)}"
        )

if __name__ == "__main__":
    logger.info("[SERVER] Starting Flex-Nautilus Migration Service v3.0.0")
    logger.info("[SERVER] Using CRIU-based migration")
    
    uvicorn.run(app, host="0.0.0.0", port=8000)

