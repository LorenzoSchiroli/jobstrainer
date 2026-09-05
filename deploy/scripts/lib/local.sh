# Local kind + Helm target. Source after lib/common.sh.
# shellcheck shell=bash

KIND_CLUSTER="${KIND_CLUSTER:-jobsifty}"
HELM_RELEASE="${HELM_RELEASE:-jobsifty}"
CHART_DIR="${REPO_ROOT}/deploy/helm/jobsifty"

_local_use_kind_context() {
  # kind writes into KUBECONFIG when it is set; unsetting it keeps local work
  # in ~/.kube/config and out of the Hetzner kubeconfig entirely.
  unset KUBECONFIG
  KUBECTL_CONTEXT="kind-${KIND_CLUSTER}"
}

_local_require_docker_daemon() {
  # The binary existing is not enough: kind, docker build and kind load all
  # need a live daemon, and each fails with its own opaque message.
  if ! docker info >/dev/null 2>&1; then
    echo "error: docker daemon is not running" >&2
    echo "hint: start Docker Desktop, then re-run" >&2
    exit 1
  fi
}

_local_ensure_cluster() {
  if kind get clusters 2>/dev/null | grep -qx "${KIND_CLUSTER}"; then
    echo "kind cluster ${KIND_CLUSTER} already exists"
    return
  fi
  echo "==> kind create cluster --name ${KIND_CLUSTER}"
  kind create cluster --name "${KIND_CLUSTER}"
}

_local_build_images() {
  echo "==> building :local images"
  docker build -f "${REPO_ROOT}/backend/Dockerfile" \
    -t jobsifty-backend:local "${REPO_ROOT}"
  docker build -f "${REPO_ROOT}/ingestion/Dockerfile" \
    -t jobsifty-ingestion:local "${REPO_ROOT}"
  # localhost:8000 matches the port-forward below and compose's CORS allow-list.
  docker build -f "${REPO_ROOT}/frontend/Dockerfile" \
    --build-arg VITE_API_URL=http://localhost:8000 \
    -t jobsifty-frontend:local "${REPO_ROOT}/frontend"

  echo "==> kind load docker-image"
  kind load docker-image \
    jobsifty-backend:local \
    jobsifty-ingestion:local \
    jobsifty-frontend:local \
    --name "${KIND_CLUSTER}"
}

_local_ensure_metrics_server() {
  if kctl get deploy metrics-server -n kube-system >/dev/null 2>&1; then
    echo "metrics-server already installed"
    return
  fi
  echo "==> installing metrics-server (required by the API HPA)"
  kctl apply -f \
    https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
  # kind-only: kind's kubelet serving cert is not signed by the cluster CA.
  # Applied once, on install, so the arg is never appended twice.
  kctl patch deployment metrics-server -n kube-system --type='json' \
    -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]'
  kctl rollout status deployment metrics-server -n kube-system --timeout=120s
}

local_up() {
  require_cmd docker
  require_cmd kind
  require_cmd kubectl
  require_cmd helm

  _local_require_docker_daemon
  _local_use_kind_context
  _local_ensure_cluster
  _local_build_images
  _local_ensure_metrics_server
  ensure_secret

  echo "==> helm upgrade --install"
  helm --kube-context "${KUBECTL_CONTEXT}" upgrade --install "${HELM_RELEASE}" "${CHART_DIR}" \
    -f "${CHART_DIR}/values.yaml" \
    -f "${CHART_DIR}/values-local.yaml"

  echo "==> waiting for ${POSTGRES_POD}"
  kctl wait --for=condition=Ready "pod/${POSTGRES_POD}" --timeout=300s

  echo "==> waiting for bootstrap Job"
  if kctl get job "${HELM_RELEASE}-bootstrap" >/dev/null 2>&1; then
    kctl wait --for=condition=complete "job/${HELM_RELEASE}-bootstrap" --timeout=600s
  fi

  cat <<HINT

local up complete. Port-forward to reach the stack:

  kubectl --context ${KUBECTL_CONTEXT} port-forward svc/api 8000:8000 &
  kubectl --context ${KUBECTL_CONTEXT} port-forward svc/frontend 3000:80 &

then open http://localhost:3000
HINT
}

local_down() {
  require_cmd kubectl
  require_cmd helm

  _local_use_kind_context
  if ! kctl cluster-info >/dev/null 2>&1; then
    echo "kind cluster ${KIND_CLUSTER} is not running; nothing to uninstall"
    return
  fi

  echo "==> helm uninstall ${HELM_RELEASE}"
  helm --kube-context "${KUBECTL_CONTEXT}" uninstall "${HELM_RELEASE}"

  cat <<HINT

local down complete. PVCs survive, so Postgres/OpenSearch data is still there.
To discard the cluster and its data entirely:

  kind delete cluster --name ${KIND_CLUSTER}
HINT
}
