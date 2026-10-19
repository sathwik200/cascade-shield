"""Custom CSS styles and UI theme for Cascade Shield Streamlit dashboard."""

def get_custom_css() -> str:
    return """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&family=Outfit:wght@500;600;700;800&display=swap');

    :root {
        --bg-main: #070913;
        --bg-card: #0d1226;
        --bg-card-hover: #131b38;
        --border-glass: rgba(255, 255, 255, 0.08);
        --accent-cyan: #00f2fe;
        --accent-blue: #4facfe;
        --accent-purple: #7928ca;
        --accent-emerald: #00e676;
        --accent-amber: #ffab00;
        --accent-crimson: #ff1744;
        --text-primary: #f0f4fc;
        --text-secondary: #94a3b8;
        --text-muted: #64748b;
    }

    /* Streamlit overrides */
    .stApp {
        background: radial-gradient(circle at 15% 15%, #0f172a 0%, #070913 70%, #030408 100%);
        font-family: 'Inter', -apple-system, sans-serif;
        color: var(--text-primary);
    }

    h1, h2, h3, h4 {
        font-family: 'Outfit', sans-serif !important;
        letter-spacing: -0.02em;
        font-weight: 700;
    }

    /* Glass card container */
    .cs-card {
        background: rgba(13, 18, 38, 0.7);
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 14px;
        padding: 20px 24px;
        box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
        transition: transform 0.2s ease, border-color 0.2s ease;
        margin-bottom: 16px;
    }
    .cs-card:hover {
        border-color: rgba(79, 172, 254, 0.3);
        transform: translateY(-2px);
    }

    /* Header banner */
    .cs-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        background: linear-gradient(135deg, rgba(13, 18, 38, 0.9) 0%, rgba(20, 27, 56, 0.9) 100%);
        border: 1px solid rgba(79, 172, 254, 0.2);
        border-radius: 16px;
        padding: 24px 32px;
        margin-bottom: 24px;
        box-shadow: 0 10px 40px rgba(0, 242, 254, 0.08);
    }

    .cs-title {
        font-size: 2.2rem;
        font-weight: 800;
        background: linear-gradient(135deg, #00f2fe 0%, #4facfe 50%, #9055ff 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin: 0;
        line-height: 1.1;
    }

    .cs-subtitle {
        color: #94a3b8;
        font-size: 0.95rem;
        margin-top: 6px;
        font-weight: 400;
    }

    /* Status badges */
    .badge-healthy {
        background: rgba(0, 230, 118, 0.15);
        color: #00e676;
        border: 1px solid rgba(0, 230, 118, 0.4);
        padding: 4px 10px;
        border-radius: 20px;
        font-size: 0.78rem;
        font-weight: 600;
        display: inline-flex;
        align-items: center;
        gap: 6px;
    }
    .badge-degraded {
        background: rgba(255, 171, 0, 0.15);
        color: #ffab00;
        border: 1px solid rgba(255, 171, 0, 0.4);
        padding: 4px 10px;
        border-radius: 20px;
        font-size: 0.78rem;
        font-weight: 600;
        display: inline-flex;
        align-items: center;
        gap: 6px;
    }
    .badge-failed {
        background: rgba(255, 23, 68, 0.15);
        color: #ff1744;
        border: 1px solid rgba(255, 23, 68, 0.4);
        padding: 4px 10px;
        border-radius: 20px;
        font-size: 0.78rem;
        font-weight: 600;
        display: inline-flex;
        align-items: center;
        gap: 6px;
    }
    .badge-isolated {
        background: rgba(170, 0, 255, 0.15);
        color: #d500f9;
        border: 1px solid rgba(170, 0, 255, 0.4);
        padding: 4px 10px;
        border-radius: 20px;
        font-size: 0.78rem;
        font-weight: 600;
        display: inline-flex;
        align-items: center;
        gap: 6px;
    }
    .badge-recovering {
        background: rgba(41, 121, 255, 0.15);
        color: #2979ff;
        border: 1px solid rgba(41, 121, 255, 0.4);
        padding: 4px 10px;
        border-radius: 20px;
        font-size: 0.78rem;
        font-weight: 600;
        display: inline-flex;
        align-items: center;
        gap: 6px;
    }

    /* Metric counter cards */
    .metric-box {
        background: rgba(15, 23, 42, 0.7);
        border: 1px solid rgba(255, 255, 255, 0.06);
        border-radius: 12px;
        padding: 16px;
        text-align: center;
        position: relative;
        overflow: hidden;
    }
    .metric-box::after {
        content: '';
        position: absolute;
        bottom: 0;
        left: 0;
        right: 0;
        height: 3px;
        background: linear-gradient(90deg, #00f2fe, #4facfe);
    }
    .metric-value {
        font-family: 'Outfit', sans-serif;
        font-size: 1.8rem;
        font-weight: 800;
        color: #ffffff;
        line-height: 1.2;
    }
    .metric-label {
        font-size: 0.75rem;
        font-weight: 600;
        color: #94a3b8;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin-top: 4px;
    }

    /* Event log pill */
    .event-row {
        padding: 8px 12px;
        border-radius: 8px;
        margin-bottom: 6px;
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.82rem;
        background: rgba(15, 23, 42, 0.5);
        border-left: 3px solid #64748b;
    }
    .event-CRITICAL {
        border-left-color: #ff1744;
        background: rgba(255, 23, 68, 0.08);
    }
    .event-WARNING {
        border-left-color: #ffab00;
        background: rgba(255, 171, 0, 0.08);
    }
    .event-INFO {
        border-left-color: #00e676;
        background: rgba(0, 230, 118, 0.08);
    }

    /* Buttons */
    div.stButton > button:first-child {
        background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
        color: #f8fafc;
        border: 1px solid rgba(255, 255, 255, 0.15);
        border-radius: 10px;
        padding: 8px 18px;
        font-weight: 600;
        font-family: 'Inter', sans-serif;
        transition: all 0.2s ease;
    }
    div.stButton > button:first-child:hover {
        border-color: #00f2fe;
        color: #00f2fe;
        box-shadow: 0 0 16px rgba(0, 242, 254, 0.25);
        transform: translateY(-1px);
    }

    /* Primary highlight buttons */
    div.stButton > button.primary-btn {
        background: linear-gradient(135deg, #00f2fe 0%, #4facfe 100%) !important;
        color: #030712 !important;
        font-weight: 700 !important;
        border: none !important;
    }
    </style>
    """
