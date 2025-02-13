import ftplib
import re
import pandas as pd
import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

# --- Environment Variables ---
FTP_SERVER = os.getenv('FTP_SERVER', 'loxone-miniserver.local')
FTP_USER = os.getenv('FTP_USER', 'meinbenutzer')
FTP_PASSWORD = os.getenv('FTP_PASSWORD', 'meinpasswort')
FILTER_USER = os.getenv('FILTER_USER', 'AZ999ZZ')
SMTP_SERVER = os.getenv('SMTP_SERVER')
SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
SMTP_USER = os.getenv('SMTP_USER')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD')
BILLING_EMAIL = os.getenv('BILLING_EMAIL')
ADMIN_EMAIL = os.getenv('ADMIN_EMAIL')

LOGFILE_PATH = "/log/wallbox.log"

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
        
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, [ADMIN_EMAIL], error_msg.as_string())


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
            user = match.group(2)
            energy_kwh = float(match.group(3))
            duration_min = int(match.group(4)) // 60  # Sekunden -> Minuten
            cost_eur = float(match.group(5))
            
            if user == FILTER_USER:
                data.append([timestamp, user, user, energy_kwh, duration_min, cost_eur])
    
    return pd.DataFrame(data, columns=["Timestamp", "User ID", "Kennzeichen", "Energie (kWh)", "Dauer (Min)", "Kosten (EUR)"])

# --- Monatswerte berechnen ---
def compute_monthly_sums(df, year, month):
    df["Monat"] = df["Timestamp"].dt.to_period("M")
    df_filtered = df[(df["Timestamp"].dt.year == year) & (df["Timestamp"].dt.month == month)]
    
    total_duration = df_filtered["Dauer (Min)"].sum()
    total_energy = df_filtered["Energie (kWh)"].sum()
    total_cost = df_filtered["Kosten (EUR)"].sum()
    
    return {
        "Gesamtdauer Laden": total_duration,
        "Gesamte Lademenge": total_energy,
        "Kostenersatz": total_cost,
        "Sessions": df_filtered
    }

# --- PDF-Bericht erstellen ---
def create_pdf_report(year, month, data, user, filename=None):
    if filename is None:
        filename = f"Kostenersatz-{user}-{month}-{year}.pdf"
    
    c = canvas.Canvas(filename, pagesize=A4)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(100, 800, f"Wallbox Ladekosten Firmenwagen - Kennzeichen {user} - {month}/{year}")
    c.setFont("Helvetica", 12)
    c.drawString(100, 780, f"Kostenersatz \"Laden Daheim\" - {kostenersatz_dict.get(year, 'N/A')} Cent/kWh")
    
    # Tabellenkopf
    c.setFont("Helvetica-Bold", 10)
    y = 750
    headers = ["Fahrzeug verbunden", "User ID", "Kennzeichen", "Energie (kWh)", "Dauer (Min)", "Kosten (EUR)"]
    for i, header in enumerate(headers):
        c.drawString(100 + i * 80, y, header)
    
    # Tabelleninhalt
    c.setFont("Helvetica", 10)
    y -= 20
    for _, row in data["Sessions"].iterrows():
        values = [row["Timestamp"].strftime("%Y-%m-%d %H:%M"), row["User ID"], row["Kennzeichen"], row["Energie (kWh)"], row["Dauer (Min)"], row["Kosten (EUR)"]]
        for i, value in enumerate(values):
            c.drawString(100 + i * 80, y, str(value))
        y -= 20
    
    # Monatssummen
    c.setFont("Helvetica-Bold", 12)
    c.drawString(100, y - 40, "Monatssummen:")
    c.setFont("Helvetica", 12)
    c.drawString(100, y - 60, f"Gesamtdauer Laden: {data['Gesamtdauer Laden']} Min")
    c.drawString(100, y - 80, f"Gesamte Lademenge: {data['Gesamte Lademenge']} kWh")
    c.drawString(100, y - 100, f"Kostenersatz: {data['Kostenersatz']} EUR")
    
    c.save()

# --- Hauptlogik ---
if __name__ == "__main__":
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
        
        # Email versenden
        subject = f"Wallbox Abrechnung {FILTER_USER} - {aktueller_monat}/{aktuelles_jahr}"
        body = f"""Sehr geehrte Damen und Herren,

anbei die Wallbox Abrechnung für {aktueller_monat}/{aktuelles_jahr}.

Gesamtdauer Laden: {monatswerte['Gesamtdauer Laden']} Min
Gesamte Lademenge: {monatswerte['Gesamte Lademenge']} kWh
Kostenersatz: {monatswerte['Kostenersatz']} EUR

Mit freundlichen Grüßen
Ihr Wallbox Reporter"""
        
        send_email(subject, body, BILLING_EMAIL, pdf_filename)
        
    except Exception as e:
        error_msg = f"Fehler im Wallbox Reporter:\n{str(e)}"
        send_email("FEHLER: Wallbox Reporter", error_msg, ADMIN_EMAIL, is_error=True)
