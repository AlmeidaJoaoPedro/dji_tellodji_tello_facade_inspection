#!/bin/sh
# Inicia a inspeção do Tello ao entrar na sessão gráfica (chamado por ~/.config/autostart/tello-inspector.desktop)
cd "$(dirname "$0")"
sleep 5  # aguarda o kanshi posicionar as telas e o XWayland subir
exec /home/tello/tello/tello_env/bin/python -u main.py >> /home/tello/tello_inspector.log 2>&1
