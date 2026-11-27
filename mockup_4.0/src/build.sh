#!/bin/sh
# Сборка одного HTML-файла из частей
{ echo '<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{margin:0}[hidden]{display:none!important}</style></head><body>'
  cat 01_head_styles.html 02_body.html
  echo '<script>'; printf 'window.PROTO='; cat data_proto.json; echo ';'
  printf 'window.RU_PATH="'; cat data_russia_path.txt; echo '";'
  printf 'window.CITIES='; cat data_cities.json; echo ';'
  echo '</script><script>'; cat 03_app.js; echo '</script><script>'; cat 04_policy.js; echo '</script></body></html>'; } > ../oiltech-radar-4.0.html
