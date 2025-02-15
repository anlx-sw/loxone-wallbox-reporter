import ftplib
import re
import pandas as pd
import smtplib
import os
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from datetime import datetime, timedelta
from create_report import create_pdf_report

# --- Environment Variables ---
FTP_SERVER = os.getenv("FTP_SERVER", "loxone-miniserver.local")
FTP_USER = os.getenv("FTP_USER", "ftpbenutzer")
FTP_PASSWORD = os.getenv("FTP_PASSWORD", "ftppasswort")
FILTER_USER = os.getenv(
    "FILTER_USER", "AZ999ZZ"
)  # Benutzer-ID welche mit dem Kennzeichen übereinstimmen sollte
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.example.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USE_SSL = os.getenv("SMTP_USE_SSL", "False").lower() in [
    "true",
    "1",
]  # Auf True setzten wenn der Mailserver 'SSL/TLS' anstart 'Starttls' verwendet.
SMTP_USER = os.getenv("SMTP_USER", "absendebenutzer@example.com")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "smtppasswort")
BILLING_EMAIL = os.getenv("BILLING_EMAIL", "billing@example.com")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@example.com")
LOGFILE_PATH = os.getenv("LOGFILE_PATH", "/log/wallbox.log")
REPORTING_DAY = int(
    os.getenv("REPORTING_DAY", "2")
)  # An diesem Tag des Folgemonats werden die Reports versendet
MONTH_LOOKBACK = int(
    os.getenv("MONTH_LOOKBACK", "1")
)  # Monate zurück - wird immer 1 sein ausser beim debugging


# --- Header-Parameter ---
kostenersatz_dict = {2025: 35.889}  # Jahr -> Kostenersatz (Cent/kWh)


def send_email(subject, body, recipient, attachment_path=None, is_error=False):
    try:
        msg = MIMEMultipart()
        msg["From"] = SMTP_USER
        msg["To"] = recipient
        if is_error:
            recipients = [recipient]
        else:
            msg["Cc"] = ADMIN_EMAIL
            recipients = [recipient, ADMIN_EMAIL]
        msg["Subject"] = subject

        msg.attach(MIMEText(body, "plain"))

        if attachment_path and os.path.exists(attachment_path):
            with open(attachment_path, "rb") as f:
                pdf = MIMEApplication(f.read(), _subtype="pdf")
                pdf.add_header(
                    "Content-Disposition",
                    "attachment",
                    filename=os.path.basename(attachment_path),
                )
                msg.attach(pdf)

        if SMTP_USE_SSL:
            with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.sendmail(SMTP_USER, recipients, msg.as_string())
        else:
            with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                server.starttls()
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.sendmail(SMTP_USER, recipients, msg.as_string())

    except Exception as e:
        # Bei Fehlern Email an Admin
        error_msg = MIMEMultipart()
        error_msg["From"] = SMTP_USER
        error_msg["To"] = ADMIN_EMAIL
        error_msg["Subject"] = "FEHLER: Wallbox Reporter"
        error_msg.attach(
            MIMEText(f"Fehler beim Versenden der Email:\n{str(e)}", "plain")
        )

        if SMTP_USE_SSL:
            with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.sendmail(SMTP_USER, recipients, msg.as_string())
        else:
            with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                server.starttls()
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.sendmail(SMTP_USER, recipients, msg.as_string())


# --- Daten vom FTP-Server abrufen ---
def fetch_logfile():
    with ftplib.FTP(FTP_SERVER) as ftp:
        ftp.login(FTP_USER, FTP_PASSWORD)
        lines = []
        ftp.retrlines(f"RETR {LOGFILE_PATH}", lines.append)

    # BOM entfernen, falls vorhanden
    if lines and lines[0].startswith("\ufeff"):
        # [1:] bedeutet "alle Elemente außer das erste"
        lines[0] = lines[0][1:]
    return lines


# --- Logdatei parsen ---


def parse_log(lines):
    pattern_disconnect = re.compile(
        r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2};Logger Wallbox;(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}):Fahrzeug getrennt;user:([^;]+);Geladene Energie:([\d.]+)kWh;Dauer:(\d+) s;([\d.]+)€$"
    )

    data = []

    for line in lines:
        match_disconnect = pattern_disconnect.search(line)
        if match_disconnect:
            fahrzeug_getrennt = datetime.strptime(
                match_disconnect.group(1), "%Y-%m-%d %H:%M:%S"
            )
            duration_seconds = int(match_disconnect.group(4))
            fahrzeug_verbunden = fahrzeug_getrennt - timedelta(seconds=duration_seconds)
            user = match_disconnect.group(2)
            energy_kwh = float(match_disconnect.group(3))
            energy_kwh = round(energy_kwh, 2)
            duration_hours = round(duration_seconds / 3600, 2)
            cost_eur = float(match_disconnect.group(5))
            cost_eur = round(cost_eur, 2)

            if user == FILTER_USER:
                data.append(
                    [
                        fahrzeug_verbunden,
                        fahrzeug_getrennt,
                        user,
                        user,
                        energy_kwh,
                        duration_hours,
                        cost_eur,
                    ]
                )
    if data:
        return pd.DataFrame(
            data,
            columns=[
                "Fahrzeug verbunden",
                "Fahrzeug getrennt",
                "User ID",
                "Kennzeichen",
                "Energie (kWh)",
                "Dauer (Std)",
                "Kosten (EUR)",
            ],
        )
    else:
        return pd.DataFrame(
            columns=[
                "Fahrzeug verbunden",
                "Fahrzeug getrennt",
                "User ID",
                "Kennzeichen",
                "Energie (kWh)",
                "Dauer (Std)",
                "Kosten (EUR)",
            ]
        )


# --- Monatswerte berechnen ---
def compute_monthly_sums(df, year, month):
    df["Monat"] = df["Fahrzeug getrennt"].dt.to_period("M")
    df_filtered = df[
        (df["Fahrzeug getrennt"].dt.year == year)
        & (df["Fahrzeug getrennt"].dt.month == month)
    ]

    if not df_filtered.empty:

        total_duration = df_filtered["Dauer (Std)"].sum()
        total_duration = round(total_duration, 2)
        total_energy = df_filtered["Energie (kWh)"].sum()
        total_energy = round(total_energy, 2)
        total_cost = df_filtered["Kosten (EUR)"].sum()
        total_cost = round(total_cost, 2)

        return {
            "Gesamtdauer Laden": total_duration,
            "Gesamte Lademenge": total_energy,
            "Kostenersatz": total_cost,
            "Sessions": df_filtered,
        }
    else:
        return None


# --- Hauptlogik ---
def main():
    """
    Hauptfunktion des Wallbox Reporters. Diese Funktion wird in einem
    unendlichen Loop ausgeführt und prüft jeden Tag, ob das Datum für
    den Report zum Vormonat erreicht ist.
    Wenn dies der Fall ist, wird die Logdatei vom FTP-Server
    abgerufen, analysiert und ein PDF-Bericht erzeugt. Dieser wird dann
    per Email an die Rechnungsadresse gesendet.

    :raises: Exception wenn ein Fehler auftritt
    """
    last_sent_month = None
    print("Starte Wallbox Reporter...")
    print(
        "Die Monatsauswertung wird am",
        REPORTING_DAY,
        "Tag des Folgemonats ausgeführt und versendet.",
    )
    print(f"Aktuelles Datum: {datetime.now()}, REPORTING_DAY: {REPORTING_DAY}")
    while True:
        now = datetime.now()
        print(
            f"Prüfe Bedingungen: Tag {now.day}, Monat {now.month}, Last sent: {last_sent_month}"
        )
        if now.day == REPORTING_DAY and now.month != last_sent_month:
            print("Starte Verarbeitung...")
            try:
                print("Hole Logfile...")
                log_lines = fetch_logfile()
                print(f"Anzahl Logzeilen: {len(log_lines)}")

                print("Parse Logfile...")
                df = parse_log(log_lines)
                print(df)

                aktuelles_jahr, aktueller_monat = (
                    datetime.now().year,
                    datetime.now().month - MONTH_LOOKBACK,
                )
                if aktueller_monat == 0:
                    aktuelles_jahr -= 1
                    aktueller_monat = 12

                print(f"Berechne für Jahr: {aktuelles_jahr}, Monat: {aktueller_monat}")
                monatswerte = compute_monthly_sums(df, aktuelles_jahr, aktueller_monat)
                print("Monatssummen für", aktueller_monat, aktuelles_jahr, monatswerte)
                # --- Wenn der Bericht keine Daten enthält
                if monatswerte is None:
                    send_email(
                        "FEHLER: Wallbox Reporter",
                        f"Keine Daten gefunden für {aktueller_monat}/{aktuelles_jahr}",
                        ADMIN_EMAIL,
                        is_error=True,
                    )
                    time.sleep(21600)
                    continue

                pdf_filename = f"reports/Kostenersatz-{FILTER_USER}-{aktueller_monat}-{aktuelles_jahr}.pdf"
                create_pdf_report(
                    aktuelles_jahr,
                    aktueller_monat,
                    monatswerte,
                    FILTER_USER,
                    kostenersatz_dict,
                    pdf_filename,
                )
                subject = f"Wallbox Abrechnung {FILTER_USER} - {aktueller_monat}/{aktuelles_jahr}"
                body = f"Sehr geehrte Damen und Herren,\n\nanbei die Abrechnung für {aktueller_monat}/{aktuelles_jahr} für das Kennzeichen {FILTER_USER}.\n\nGesamtdauer: {monatswerte['Gesamtdauer Laden']} Stunden\nLademenge: {monatswerte['Gesamte Lademenge']} kWh\nKostenersatz: {monatswerte['Kostenersatz']} EUR\n\nMit freundlichen Grüßen\nIhr Wallbox Reporter"
                send_email(subject, body, BILLING_EMAIL, pdf_filename)
                last_sent_month = now.month
            except Exception as e:
                send_email(
                    "FEHLER: Wallbox Reporter",
                    f"Fehler: {str(e)}",
                    ADMIN_EMAIL,
                    is_error=True,
                )
        print("Sleep 6 Stunden...")
        time.sleep(21600)


if __name__ == "__main__":
    main()
