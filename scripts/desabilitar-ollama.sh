#!/usr/bin/env bash
#
# ============================================================================
#  O QUE ESTE SCRIPT FAZ
# ============================================================================
#
#  Para o serviço Ollama e o remove da inicialização automática, liberando a
#  GPU para o vLLM.
#
#  Motivo: a máquina tem RTX 3050 com 4 GB de VRAM. Ollama e vLLM rodavam juntos
#  disputando os mesmos 4 GB, então nenhuma medição de desempenho era válida.
#  Decisão registrada em ADR-015.
#
# ============================================================================
#  AÇÕES EXATAS (duas)
# ============================================================================
#
#   1. systemctl disable --now ollama
#      → tira o Ollama do boot E para o processo agora.
#      → é o único comando que altera o sistema.
#
#   2. sleep 2 && nvidia-smi (consulta)
#      → só LEITURA, para mostrar a VRAM liberada.
#
# ============================================================================
#  O QUE ESTE SCRIPT **NÃO** FAZ
# ============================================================================
#
#   ✗ não apaga o binário do Ollama (/usr/local/bin/ollama fica intacto)
#   ✗ não apaga modelos (ficam em disco, ~4,7 GB; não são tocados)
#   ✗ não remove o pacote, não mexe em /etc, não edita unit file
#   ✗ não toca em vLLM
#   ✗ não altera firewall, rede, disco ou permissões
#   ✗ não envia nada para fora
#
#  Parado, o Ollama não consome VRAM nem CPU. Reinstalar seria custo sem ganho.
#
# ============================================================================
#  COMO REVERTER
# ============================================================================
#
#   sudo bash scripts/desabilitar-ollama.sh --reativar
#     → systemctl enable --now ollama. Volta ao estado anterior.
#
#   Sem reabilitar no boot (subir só agora):
#     sudo systemctl start ollama
#
# ============================================================================
#  USO
# ============================================================================
#
#   sudo bash scripts/desabilitar-ollama.sh --dry-run   # mostra, não faz nada
#   sudo bash scripts/desabilitar-ollama.sh             # aplica
#   sudo bash scripts/desabilitar-ollama.sh --reativar  # desfaz
#
# ============================================================================

set -euo pipefail

SERVICO="ollama"
MODO="aplicar"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run|-n) MODO="simular"; shift ;;
    --reativar|--reverter|--enable) MODO="reverter"; shift ;;
    -h|--help)
      # Mostra só o cabeçalho de auditoria, que é o que importa revisar.
      sed -n '2,50p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "argumento desconhecido: $1" >&2; exit 64 ;;
  esac
done

if [[ "${EUID}" -ne 0 ]]; then
  echo "erro: este script precisa de root." >&2
  echo "      rode: sudo bash $0 $*" >&2
  echo "      para apenas ver o que faria: sudo bash $0 --dry-run" >&2
  exit 77
fi

if ! systemctl list-unit-files 2>/dev/null | grep -q "^${SERVICO}.service"; then
  echo "erro: serviço '${SERVICO}' não existe nesta máquina." >&2
  exit 1
fi

mostrar_gpu() {
  if command -v nvidia-smi >/dev/null 2>&1; then
    echo "  VRAM em uso: $(nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader)"
    local proc
    proc="$(nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader 2>/dev/null || true)"
    if [[ -n "${proc}" ]]; then
      while IFS= read -r linha; do
        echo "  processo: ${linha}"
      done <<<"${proc}"
    else
      echo "  processo: (nenhum usando GPU)"
    fi
  else
    echo "  nvidia-smi ausente"
  fi
}

echo "=================================================================="
echo " ESTADO ATUAL"
echo "=================================================================="
echo "  serviço : ${SERVICO}.service"
echo "  habilitado no boot : $(systemctl is-enabled "${SERVICO}" 2>/dev/null || echo 'não')"
echo "  rodando agora      : $(systemctl is-active "${SERVICO}" 2>/dev/null || echo 'não')"
mostrar_gpu

case "${MODO}" in
  simular)
    echo
    echo "=================================================================="
    echo " DRY-RUN — nada foi alterado"
    echo "=================================================================="
    echo "  Aplicaria exatamente isto:"
    echo "    systemctl disable --now ${SERVICO}"
    echo
    echo "  Efeito: para o processo e remove do boot."
    echo "  Não remove binário nem modelos."
    echo
    echo "  Para aplicar de verdade:"
    echo "    sudo bash $0"
    ;;

  reverter)
    echo
    echo "=================================================================="
    echo " REVERTENDO"
    echo "=================================================================="
    echo "  executando: systemctl enable --now ${SERVICO}"
    systemctl enable --now "${SERVICO}"
    echo
    echo "  habilitado no boot : $(systemctl is-enabled "${SERVICO}" 2>/dev/null)"
    echo "  rodando agora      : $(systemctl is-active "${SERVICO}" 2>/dev/null)"
    echo
    echo "  Revertido. A GPU volta a ser compartilhada entre Ollama e vLLM."
    mostrar_gpu
    ;;

  aplicar)
    echo
    echo "=================================================================="
    echo " APLICANDO"
    echo "=================================================================="
    echo "  executando: systemctl disable --now ${SERVICO}"
    systemctl disable --now "${SERVICO}"
    echo
    # Espera o processo sair de fato. `systemctl stop` retorna antes do kernel
    # liberar a VRAM; consultar imediatamente mostraria memória ainda ocupada e
    # daria a impressão de que o script não funcionou.
    sleep 2

    echo "=================================================================="
    echo " DEPOIS"
    echo "=================================================================="
    echo "  habilitado no boot : $(systemctl is-enabled "${SERVICO}" 2>/dev/null || echo 'não (correto)')"
    echo "  rodando agora      : $(systemctl is-active "${SERVICO}" 2>/dev/null || echo 'não (correto)')"
    mostrar_gpu

    echo
    echo "=================================================================="
    echo " PRONTO"
    echo "=================================================================="
    cat <<'FIM'
  O Ollama está parado e não sobe mais no boot.
  Nada foi apagado: binário e modelos continuam em disco.

  Subir só agora, sem reabilitar no boot:
    sudo systemctl start ollama

  Derrubar de novo:
    sudo systemctl stop ollama

  Desfazer completamente:
    sudo bash scripts/desabilitar-ollama.sh --reativar

  ATENÇÃO: se a VRAM acima ainda mostra uso, é o vLLM (VLLM::EngineCore).
  Confira se é o processo que você quer manter.
FIM
    ;;
esac
