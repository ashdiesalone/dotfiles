#!/bin/bash

AC=$(cat /sys/class/power_supply/ACAD/online 2>/dev/null || echo "0")

if [ "$AC" = "1" ]; then
    echo '{"text": "ac", "tooltip": "TLP: Perfil AC (cargador)", "class": "ac"}'
else
    echo '{"text": "bat", "tooltip": "TLP: Perfil batería", "class": "bat"}'
fi

