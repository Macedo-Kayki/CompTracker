PT = {
    "Argentina": "Argentina", "Australia": "Austrália", "Austria": "Áustria", "Bahrain": "Bahrein",
    "Belarus": "Bielorrússia", "Belgium": "Bélgica", "Bolivia": "Bolívia", "Brazil": "Brasil",
    "Bulgaria": "Bulgária", "Cambodia": "Camboja", "Canada": "Canadá", "Chile": "Chile", "China": "China",
    "Colombia": "Colômbia", "Costa Rica": "Costa Rica", "Croatia": "Croácia", "Cyprus": "Chipre",
    "Czech Republic": "República Tcheca", "Czechia": "República Tcheca", "Denmark": "Dinamarca",
    "Dominican Republic": "República Dominicana", "Ecuador": "Equador", "Egypt": "Egito", "Estonia": "Estônia",
    "Europe": "Europa", "Finland": "Finlândia", "France": "França", "Germany": "Alemanha", "Greece": "Grécia",
    "Guatemala": "Guatemala", "Hong Kong": "Hong Kong", "Hungary": "Hungria", "Iceland": "Islândia",
    "India": "Índia", "Indonesia": "Indonésia", "International": "Internacional", "Iran": "Irã", "Iraq": "Iraque",
    "Ireland": "Irlanda", "Israel": "Israel", "Italy": "Itália", "Japan": "Japão", "Jordan": "Jordânia",
    "Kazakhstan": "Cazaquistão", "Kuwait": "Kuwait", "Latvia": "Letônia", "Lebanon": "Líbano",
    "Lithuania": "Lituânia", "Macau": "Macau", "Malaysia": "Malásia", "Mexico": "México", "Mongolia": "Mongólia",
    "Morocco": "Marrocos", "Netherlands": "Países Baixos", "New Zealand": "Nova Zelândia", "Norway": "Noruega",
    "Oman": "Omã", "Pakistan": "Paquistão", "Panama": "Panamá", "Paraguay": "Paraguai", "Peru": "Peru",
    "Philippines": "Filipinas", "Poland": "Polônia", "Portugal": "Portugal", "Puerto Rico": "Porto Rico",
    "Qatar": "Catar", "Romania": "Romênia", "Russia": "Rússia", "Saudi Arabia": "Arábia Saudita",
    "Serbia": "Sérvia", "Singapore": "Singapura", "Slovakia": "Eslováquia", "Slovenia": "Eslovênia",
    "South Africa": "África do Sul", "South Korea": "Coreia do Sul", "Korea": "Coreia do Sul", "Spain": "Espanha",
    "Sweden": "Suécia", "Switzerland": "Suíça", "Taiwan": "Taiwan", "Thailand": "Tailândia", "Tunisia": "Tunísia",
    "Turkey": "Turquia", "Türkiye": "Turquia", "Ukraine": "Ucrânia", "United Arab Emirates": "Emirados Árabes",
    "United Kingdom": "Reino Unido", "United States": "Estados Unidos", "Uruguay": "Uruguai",
    "Venezuela": "Venezuela", "Vietnam": "Vietnã", "North America": "América do Norte",
    "Latin America": "América Latina", "Asia-Pacific": "Ásia-Pacífico", "MENA": "MENA", "CIS": "CEI",
}


def pt(name):
    """Traduz o nome de um país ou região para português."""
    if not isinstance(name, str) or not name:
        return None
    return PT.get(name, name)
