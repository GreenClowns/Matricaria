#!/usr/bin/env bash
# Полный прогон эксперимента: модели параллельно, затем судьи, затем таблица.
#
#   bash run_all.sh --fresh   # начать заново
#   bash run_all.sh           # продолжить с места остановки
#
# Журналы — в results/log-*.txt, итоговая таблица — в results/tables.md.
# Окно терминала не закрывать, пока не появится таблица.

cd "$(dirname "$0")" || exit 1
FRESH="${1:-}"
MODELS="A B gemma"

# Кто кого судит: модели проверяют друг друга, а не сами себя.
judge_for() {
  case "$1" in
    A) echo B ;;
    *) echo A ;;
  esac
}

for m in $MODELS; do
  python3 -u run.py --model "$m" $FRESH > "results/log-$m.txt" 2>&1 &
done
wait
echo "=== Прогоны закончены ==="
for m in $MODELS; do
  echo "--- $m: $(tail -n 1 "results/log-$m.txt")"
done

for m in $MODELS; do
  python3 -u judge.py "results/$m.jsonl" --judge "$(judge_for "$m")" > "results/log-judge-$m.txt" 2>&1 &
done
wait
echo "=== Оценка закончена ==="

files=""
for m in $MODELS; do files="$files results/$m.jsonl"; done
python3 report.py $files | tee results/tables.md
