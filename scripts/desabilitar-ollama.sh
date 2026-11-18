#!/usr/bin/env bash
# Desabilita o Ollama permanentemente e libera a GPU para o vLLM.
#
# CONTEXTO: a máquina tem RTX 3050 com 4 GB de VRAM. Ollama e vLLM disputavam os
# mesmos 4 GB, e no ADR-010 a escolha foi vLLM por dois motivos concretos:
# teto de memória explícito (`--gpu-memory-utilization`) e batching contínuo.
# Ollama fica disponível para subir sob demanda quando fizer falta.
#
# "Desabilitar permanentemente" aqui significa: não sobe no boot e não fica
# rodando. O binário e os modelos NÃO são removidos — `ollama serve` volta quando
# você quiser.
#
# USO:
#   sudo bash scripts/desabilitar-ollama.sh
#   sudo bash scripts/desabilitar-ollama.sh --reativar   # volta ao estado anterior

set -euo pipefail

REATIVAR=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --reativar|--enable) REATIVAR=1; shift ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    *) echo "argumento desconhecido: $1" >&2; exit 64 ;;
  esac
done

if [[ "${EUID}" -ne 0 ]]; then
  echo "erro: precisa de root. Rode com sudo:" >&2
  echo "  sudo bash $0 ${*:-}" >&2
  exit 77
fi

mostrar_gpu() {
  if command -v nvidia-smi >/dev/null 2>&1; then
    echo "  VRAM: $(nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader)"
    nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader \
      | sed 's/^/  proc: /' || true
  fi
}

if (( REATIVAR )); then
  echo "== reativando ollama =="
  systemctl enable --now ollama
  systemctl is-active ollama
  echo "ollama ativo. A GPU volta a ser disputada."
  mostrar_gpu
  exit 0
fi

echo "=============================================================="
echo " ANTES"
echo "=============================================================="
systemctl is-enabled ollama 2>/dev/null || echo "  (não habilitado)"
systemctl is-active ollama 2>/dev/null || echo "  (inativo)"
mostrar_gpu

echo
echo "=============================================================="
echo " DESABILITANDO"
echo "=============================================================="
# `disable --now` faz as duas coisas: tira do boot e para agora. Um comando só
# evita o estado intermediário "parado mas habilitado", que volta no reboot.
systemctl disable --now ollama
echo "  ollama parado e removido do boot"

# Descrica o modelo em memoria, se ainda houver. `ollama stop` só funciona com o
# servidor de pé, então não serve aqui — o VRAM é liberado no kill do processo.
sleep 2

echo
echo "=============================================================="
echo " DEPOIS"
echo "=============================================================="
systemctl is-enabled ollama 2>/dev/null || echo "  enabled: não (correto)"
systemctl is-active ollama 2>/dev/null || echo "  active: não (correto)"
mostrar_gpu

echo
echo "=============================================================="
echo " PRÓXIMO PASSO"
echo "=============================================================="
cat <<'FIM'
  O Ollama não sobe mais no boot e não está rodando. O binário e os modelos
  continuam em disco — para usar sob demanda:

    sudo systemctl start ollama     # sobe agora, sem reabilitar no boot
    ollama list                     # modelos continuam lá
    sudo systemctl stop ollama      # derruba de novo

  Para desfazer tudo:

    sudo bash scripts/desabilitar-ollama.sh --reativar

  ATENÇÃO: o vLLM que estava rodando (VLLM::EngineCore) também consumia ~3.5 GB.
  Confira se ele é o que você quer manter antes de subir o módulo de chat.
FIM
