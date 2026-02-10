"""Costanti."""

DOMAIN = "ksenia_lares"

# Stati delle zone
ZONE_STATUS_IDLE = "IDLE"  # Zona a riposo (Chiusa / Nessun movimento)
ZONE_STATUS_ALARM = "ALARM"  # Zona in allarme (Aperta / Movimento rilevato)
ZONE_STATUS_TILT = "TILT"  # Vasistas
ZONE_STATUS_TAMPER = "TAMPER"  # Sabotaggio
ZONE_STATUS_UNKNOWN = "UNKNOWN"  # Stato sconosciuto
DEFAULT_SCAN_INTERVAL = 30  # Secondi
