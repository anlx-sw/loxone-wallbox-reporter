import ftplib
import re
import pandas as pd
import smtplib
import os
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.pagesizes import landscape
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.units import cm

# --- Environment Variables ---
FTP_SERVER = os.getenv('FTP_SERVER', 'loxone-miniserver.local')
FTP_USER = os.getenv('FTP_USER', 'ftpbenutzer')
FTP_PASSWORD = os.getenv('FTP_PASSWORD', 'ftppasswort')
FILTER_USER = os.getenv('FILTER_USER', 'AZ999ZZ')
SMTP_SERVER = os.getenv('SMTP_SERVER','smtp.example.com')
SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
SMTP_USE_SSL = os.getenv('SMTP_USE_SSL', 'False').lower() in ['true', '1'] # Auf True setzten wenn der Mailserver 'SSL/TLS' anstart 'Starttls' verwendet.
SMTP_USER = os.getenv('SMTP_USER', 'absendebenutzer@example.com')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', 'smtppasswort')
BILLING_EMAIL = os.getenv('BILLING_EMAIL', 'billing@example.com')
ADMIN_EMAIL = os.getenv('ADMIN_EMAIL', 'admin@example.com')
LOGFILE_PATH = os.getenv('LOGFILE_PATH', '"/log/wallbox.log"')

# --- Header-Parameter ---
kostenersatz_dict = {2025: 35.889}  # Jahr -> Kostenersatz (Cent/kWh)

def send_email(subject, body, recipient, attachment_path=None, is_error=False):
    try:
        msg = MIMEMultipart()
        msg['From'] = SMTP_USER
        msg['To'] = recipient
        if is_error:
            msg['Cc'] = ADMIN_EMAIL
            recipients = [recipient, ADMIN_EMAIL]
        else:
            msg['Cc'] = ADMIN_EMAIL
            recipients = [recipient, ADMIN_EMAIL]
        msg['Subject'] = subject

        msg.attach(MIMEText(body, 'plain'))

        if attachment_path and os.path.exists(attachment_path):
            with open(attachment_path, 'rb') as f:
                pdf = MIMEApplication(f.read(), _subtype='pdf')
                pdf.add_header('Content-Disposition', 'attachment', 
                             filename=os.path.basename(attachment_path))
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
        error_msg['From'] = SMTP_USER
        error_msg['To'] = ADMIN_EMAIL
        error_msg['Subject'] = 'FEHLER: Wallbox Reporter'
        error_msg.attach(MIMEText(f'Fehler beim Versenden der Email:\n{str(e)}', 'plain'))
        
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
        ftp.retrlines(f'RETR {LOGFILE_PATH}', lines.append)
    return lines

# --- Logdatei parsen ---
def parse_log(lines):
    pattern = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2});.*?user:(.*?);Geladene Energie:(\d+\.\d+)kWh;Dauer:(\d+) s;(\d+\.\d+)€;")
    data = []
    
    for line in lines:
        match = pattern.search(line)
        if match:
            timestamp = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S")
            fahrzeug_verbunden = timestamp
            fahrzeug_getrennt = timestamp
            user = match.group(2)
            energy_kwh = float(match.group(3))
            duration_hours = int(match.group(4)) // 3600  # Sekunden -> Stunden
            cost_eur = float(match.group(5))
            
            if user == FILTER_USER:
                data.append([timestamp, fahrzeug_verbunden, fahrzeug_getrennt, user, user, energy_kwh, duration_hours, cost_eur])
    
    return pd.DataFrame(data, columns=["Timestamp","Fahrzeug verbunden","Fahrzeug getrennt", "User ID", "Kennzeichen", "Energie (kWh)", "Dauer (Std)", "Kosten (EUR)"])

# --- Monatswerte berechnen ---
def compute_monthly_sums(df, year, month):
    df["Monat"] = df["Timestamp"].dt.to_period("M")
    df_filtered = df[(df["Timestamp"].dt.year == year) & (df["Timestamp"].dt.month == month)]

    total_duration = df_filtered["Dauer (Std)"].sum()
    total_energy = df_filtered["Energie (kWh)"].sum()
    total_cost = df_filtered["Kosten (EUR)"].sum()
    
    return {
        "Gesamtdauer Laden": total_duration,
        "Gesamte Lademenge": total_energy,
        "Kostenersatz": total_cost,
        "Sessions": df_filtered
    }

# --- PDF-Bericht erstellen --
def create_pdf_report(year, month, data, user, filename=None):
    if filename is None:
        filename = f"Kostenersatz-{user}-{month}-{year}.pdf"
    os.makedirs("reports", exist_ok=True)
    c = canvas.Canvas(filename, pagesize=landscape(A4))
    
    # Platz für das Logo oben rechts
    logo_path = "logo.png"  # Falls ein Logo existiert, hier den Pfad anpassen
    if os.path.exists(logo_path):
        c.drawImage(logo_path, 26 * cm, 19 * cm, width=4 * cm, height=2 * cm)
    
    # Titel und Einleitung
    c.setFont("Helvetica-Bold", 16)
    c.setFillColor(colors.HexColor("#68B300"))  # Loxone-Grün
    c.drawString(2 * cm, 19.5 * cm, f"Wallbox Ladekosten Firmenwagen - Kennzeichen {user} - {month}/{year}")
    c.setFont("Helvetica", 12)
    c.setFillColor(colors.black)
    c.drawString(2 * cm, 18.5 * cm, f"Kostenersatz {year} \"Laden Daheim\" - {kostenersatz_dict.get(year, 'N/A')} Cent/kWh")
    
    # Tabellenkopf mit Hintergrundfarbe
    c.setFont("Helvetica-Bold", 8)  # Schrift verkleinert zur besseren Lesbarkeit
    y = 17.5 * cm
    headers = ["Ende Ladesession", "Fahrzeug verbunden", "Fahrzeug getrennt", "User ID", "Kennzeichen", "Dauer (Std)", "Energie (kWh)", "Kosten (EUR)"]
    column_widths = [90, 90, 90, 50, 80, 70, 70, 70]  # Optimierte Spaltenbreiten
    x_positions = [2 * cm]
    for width in column_widths:
        x_positions.append(x_positions[-1] + width)
    
    c.setFillColor(colors.HexColor("#68B300"))  # Loxone-Grün
    c.rect(2 * cm, y - 5, sum(column_widths), 15, fill=1, stroke=0)
    c.setFillColor(colors.white)
    for i, header in enumerate(headers):
        c.drawString(x_positions[i] + 5, y, header)
    
    # Tabelleninhalt mit Seitenumbruch
    c.setFont("Helvetica", 8)
    c.setFillColor(colors.black)
    y -= 20
    row_height = 12
    max_y = 2 * cm  # Grenze für Seitenumbruch
    for _, row in data["Sessions"].iterrows():
        if y < max_y:
            c.showPage()
            y = 17.5 * cm  # Neue Seite, Startpunkt setzen
            c.setFont("Helvetica-Bold", 8)
            c.setFillColor(colors.HexColor("#68B300"))
            c.rect(2 * cm, y - 5, sum(column_widths), 15, fill=1, stroke=0)
            c.setFillColor(colors.white)
            for i, header in enumerate(headers):
                c.drawString(x_positions[i] + 5, y, header)
            c.setFont("Helvetica", 8)
            c.setFillColor(colors.black)
            y -= 20
        
        values = [
            row["Timestamp"].strftime("%Y-%m-%d %H:%M"), row["Fahrzeug verbunden"], row["Fahrzeug getrennt"],
            row["User ID"], row["Kennzeichen"], f"{row['Dauer (Std)']:.2f}", row["Energie (kWh)"], row["Kosten (EUR)"]
        ]
        c.setFillColor(colors.lightgrey if _ % 2 == 0 else colors.white)
        c.rect(2 * cm, y - 5, sum(column_widths), row_height, fill=1, stroke=0)
        c.setFillColor(colors.black)
        for i, value in enumerate(values):
            c.drawString(x_positions[i] + 5, y, str(value))
        y -= row_height
    
    # Monatssummen
    c.setFont("Helvetica-Bold", 12)
    c.setFillColor(colors.HexColor("#68B300"))
    c.drawString(2 * cm, y - 40, "Monatssummen:")
    c.setFont("Helvetica", 12)
    c.setFillColor(colors.black)
    c.drawString(2 * cm, y - 60, f"Gesamtdauer Laden: {data['Gesamtdauer Laden']:.2f} Std")
    c.drawString(2 * cm, y - 80, f"Gesamte Lademenge: {data['Gesamte Lademenge']} kWh")
    c.drawString(2 * cm, y - 100, f"Kostenersatz: {data['Kostenersatz']} EUR")
    
    c.save()


# --- Hauptlogik ---
def main():
    """
    Hauptfunktion des Wallbox Reporters. Diese Funktion wird in einem
    unendlichen Loop ausgeführt und prüft jeden Tag, ob ein neuer Monat
    begonnen hat. Wenn dies der Fall ist, wird die Logdatei vom FTP-Server
    abgerufen, analysiert und ein PDF-Bericht erzeugt. Dieser wird dann
    per Email an die Rechnungsadresse gesendet.

    :raises: Exception wenn ein Fehler auftritt
    """
    last_sent_month = None
    print("Starte Wallbox Reporter...")
    while True:
        now = datetime.now()
        if now.day == 14 and now.month != last_sent_month:
            try:
                log_lines = fetch_logfile()
                df = parse_log(log_lines)
                aktuelles_jahr, aktueller_monat = datetime.now().year, datetime.now().month - 1
                if aktueller_monat == 0:
                        aktuelles_jahr -= 1
                        aktueller_monat = 12

                monatswerte = compute_monthly_sums(df, aktuelles_jahr, aktueller_monat)
                print("Monatssummen für", aktueller_monat, aktuelles_jahr, monatswerte)
                pdf_filename = f"reports/Kostenersatz-{FILTER_USER}-{aktueller_monat}-{aktuelles_jahr}.pdf"
                create_pdf_report(aktuelles_jahr, aktueller_monat, monatswerte, FILTER_USER, pdf_filename)
                subject = f"Wallbox Abrechnung {FILTER_USER} - {aktueller_monat}/{aktuelles_jahr}"
                body = f"Sehr geehrte Damen und Herren,\n\nanbei die Abrechnung für {aktueller_monat}/{aktuelles_jahr}.\n\nGesamtdauer: {monatswerte['Gesamtdauer Laden']} Min\nLademenge: {monatswerte['Gesamte Lademenge']} kWh\nKosten: {monatswerte['Kostenersatz']} EUR\n\nMit freundlichen Grüßen\nIhr Wallbox Reporter"
                send_email(subject, body, BILLING_EMAIL, pdf_filename)
                last_sent_month = now.month
            except Exception as e:
                send_email("FEHLER: Wallbox Reporter", f"Fehler: {str(e)}", ADMIN_EMAIL, is_error=True)
        time.sleep(21600)

if __name__ == "__main__":
    main()