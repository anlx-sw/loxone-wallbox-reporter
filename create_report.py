import os
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.units import cm


def create_pdf_report(year, month, data, user, kostenersatz_dict, filename=None):
    if filename is None:
        filename = f"Kostenersatz-{user}-{month}-{year}.pdf"
    os.makedirs("reports", exist_ok=True)
    c = canvas.Canvas(filename, pagesize=landscape(A4))

    # Logo oben rechts
    logo_path = "logo.png"
    if os.path.exists(logo_path):
        c.drawImage(logo_path, 26 * cm, 19 * cm, width=4 * cm, height=2 * cm)

    # Titel
    c.setFont("Helvetica-Bold", 18)
    c.setFillColor(colors.HexColor("#68B300"))
    c.drawString(2 * cm, 19 * cm, f"Wallbox Ladekosten - {user} - {month}/{year}")
    c.setFont("Helvetica", 12)
    c.setFillColor(colors.black)
    c.drawString(
        2 * cm,
        18 * cm,
        f"Kostenersatz {year}: {kostenersatz_dict.get(year, 'N/A')} Cent/kWh",
    )

    # Tabellenkopf
    headers = [
        "Verbunden",
        "Getrennt",
        "User ID",
        "Kennzeichen",
        "Dauer (Std)",
        "Energie (kWh)",
        "Kosten (EUR)",
    ]
    column_widths = [110, 110, 70, 100, 80, 80, 80]
    x_positions = [2 * cm]
    for width in column_widths:
        x_positions.append(x_positions[-1] + width)

    y = 17 * cm
    c.setFillColor(colors.HexColor("#68B300"))
    c.rect(2 * cm, y - 10, sum(column_widths), 15, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 10)
    for i, header in enumerate(headers):
        c.drawString(x_positions[i] + 5, y - 5, header)

    # Tabelleninhalt mit alternierender Zeilenfarbe
    c.setFont("Helvetica", 9)
    y -= 20
    row_height = 14
    max_y = 2 * cm

    for idx, row in data["Sessions"].iterrows():
        if y < max_y:
            c.showPage()
            y = 17 * cm
            c.setFont("Helvetica-Bold", 10)
            c.setFillColor(colors.HexColor("#68B300"))
            c.rect(2 * cm, y - 10, sum(column_widths), 15, fill=1, stroke=0)
            c.setFillColor(colors.white)
            for i, header in enumerate(headers):
                c.drawString(x_positions[i] + 5, y - 5, header)
            c.setFont("Helvetica", 9)
            y -= 20

        bg_color = colors.HexColor("#DFF0D8") if idx % 2 == 0 else colors.white
        c.setFillColor(bg_color)
        c.rect(2 * cm, y - 5, sum(column_widths), row_height, fill=1, stroke=0)
        c.setFillColor(colors.black)
        values = [
            row["Fahrzeug verbunden"],
            row["Fahrzeug getrennt"],
            row["User ID"],
            row["Kennzeichen"],
            f"{row['Dauer (Std)']:.2f}",
            row["Energie (kWh)"],
            row["Kosten (EUR)"],
        ]
        for i, value in enumerate(values):
            c.drawString(x_positions[i] + 5, y, str(value))
        y -= row_height

    # Monatssummen
    y -= 20
    c.setFont("Helvetica-Bold", 12)
    c.setFillColor(colors.HexColor("#68B300"))
    c.drawString(2 * cm, y, "Monatssummen:")
    c.setFont("Helvetica", 10)
    c.setFillColor(colors.black)
    c.drawString(2 * cm, y - 20, f"Gesamtdauer: {data['Gesamtdauer Laden']} Std")
    c.drawString(2 * cm, y - 40, f"Lademenge: {data['Gesamte Lademenge']} kWh")
    c.drawString(2 * cm, y - 60, f"Kostenersatz: {data['Kostenersatz']} EUR")

    c.save()
