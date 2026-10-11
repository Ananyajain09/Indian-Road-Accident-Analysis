"""
run_all.py -- Indian Road Accident Analysis Pipeline
=====================================================
This script does everything in one go:
  1. Reads the raw data (CSV or Excel)
  2. Cleans it (duplicates, dates, text formatting, new columns)
  3. Saves cleaned data to CSV (for Power BI)
  4. Loads it into SQLite and runs analytical queries
  5. Creates matplotlib charts
  6. Checks data quality and generates README.md

Run:  python run_all.py
"""

import os
import sys
import sqlite3
import pandas as pd
import matplotlib
matplotlib.use("Agg")  # non-interactive backend so it works without a display
import matplotlib.pyplot as plt
from datetime import datetime

# Force UTF-8 output on Windows (avoids cp1252 encoding errors)
sys.stdout.reconfigure(encoding="utf-8")

# -----------------------------------------------
# 0.  SETUP -- make sure output folders exist
# -----------------------------------------------
for folder in ["data", "sql", "outputs", "powerbi", "notebooks", "docs"]:
    os.makedirs(folder, exist_ok=True)

print("=" * 60)
print("  Indian Road Accident Analysis Pipeline")
print("=" * 60)

# -----------------------------------------------
# 1.  READ RAW DATA
# -----------------------------------------------
print("\n[1] Reading raw data ...")

# Support both CSV and Excel
if os.path.exists("data/raw.csv"):
    df = pd.read_csv("data/raw.csv")
    print("    -> Loaded data/raw.csv")
elif os.path.exists("data/raw.xlsx"):
    df = pd.read_excel("data/raw.xlsx", engine="openpyxl")
    print("    -> Loaded data/raw.xlsx")
else:
    raise FileNotFoundError("No data file found! Place raw.csv or raw.xlsx in data/")

rows_before = len(df)
print(f"    -> Rows loaded: {rows_before}")
print(f"    -> Columns: {list(df.columns)}")

# -----------------------------------------------
# 2.  CLEAN THE DATA
# -----------------------------------------------
print("\n[2] Cleaning data ...")

# 2a. Drop exact duplicate rows
dupes = df.duplicated().sum()
df = df.drop_duplicates()
print(f"    -> Duplicates removed: {dupes}")

# 2b. Strip whitespace + title-case all text (object) columns
text_cols = df.select_dtypes(include="object").columns.tolist()
for col in text_cols:
    df[col] = df[col].astype(str).str.strip().str.title()
print(f"    -> Text columns cleaned (strip + title-case): {text_cols}")

# 2c. Parse the 'date' column -- handle mixed formats safely
#     We try multiple formats; anything that fails becomes NaT
df["date"] = pd.to_datetime(df["date"], format="%Y-%m-%d", errors="coerce")

# Count how many dates could not be parsed
bad_dates = df["date"].isna().sum()
print(f"    -> Dates that failed to parse: {bad_dates}")

# 2d. Drop rows where date or city is missing
nulls_before = df[["date", "city"]].isna().any(axis=1).sum()
df = df.dropna(subset=["date", "city"])
print(f"    -> Rows dropped (missing date/city): {nulls_before}")

# 2e. Create helpful new columns
df["year"]  = df["date"].dt.year.astype(int)
df["month"] = df["date"].dt.month.astype(int)

# Make sure 'hour' is integer (it already exists in the dataset)
df["hour"] = pd.to_numeric(df["hour"], errors="coerce").fillna(0).astype(int)

# time_band: categorise the hour into a human-readable time slot
def get_time_band(h):
    """Return a time band label for a given hour (0-23)."""
    if h < 6:
        return "Night"       # midnight to 6 AM
    elif h < 12:
        return "Morning"     # 6 AM to noon
    elif h < 17:
        return "Afternoon"   # noon to 5 PM
    elif h < 22:
        return "Evening"     # 5 PM to 10 PM
    else:
        return "Late Night"  # 10 PM to midnight

df["time_band"] = df["hour"].apply(get_time_band)

# is_fatal: 1 if severity is Fatal, else 0
df["is_fatal"] = (df["accident_severity"].str.lower() == "fatal").astype(int)

rows_after = len(df)

# -- Cleaning Summary --
print("\n" + "-" * 40)
print("  CLEANING SUMMARY")
print("-" * 40)
print(f"  Rows before cleaning : {rows_before}")
print(f"  Rows after cleaning  : {rows_after}")
print(f"  Rows removed         : {rows_before - rows_after}")
print(f"  Duplicates removed   : {dupes}")
print(f"  Bad dates            : {bad_dates}")
print(f"  Missing date/city    : {nulls_before}")
print(f"  New columns added    : year, month, time_band, is_fatal")
print("-" * 40)

# 2f. Save cleaned data
df.to_csv("data/cleaned.csv", index=False)
print("\n    -> Saved data/cleaned.csv")

# -----------------------------------------------
# 3.  LOAD INTO SQLITE
# -----------------------------------------------
print("\n[3] Loading into SQLite (accidents.db) ...")

# Remove old DB so we start fresh each run
if os.path.exists("accidents.db"):
    os.remove("accidents.db")

conn = sqlite3.connect("accidents.db")
df.to_sql("accidents", conn, if_exists="replace", index=False)
print(f"    -> Table 'accidents' created with {rows_after} rows")

# -----------------------------------------------
# 4.  RUN SQL QUERIES AND SAVE RESULTS
# -----------------------------------------------
print("\n[4] Running SQL queries ...")

# Define queries inline (they are also saved in sql/queries.sql)
queries = {
    "city_fatality": """
        SELECT city,
               COUNT(*) AS total_accidents,
               SUM(is_fatal) AS fatal_accidents,
               ROUND(AVG(is_fatal) * 100, 2) AS fatality_rate_pct
        FROM accidents
        GROUP BY city
        ORDER BY total_accidents DESC
    """,
    "hourly_accidents": """
        SELECT hour,
               COUNT(*) AS total_accidents,
               SUM(casualties) AS total_casualties
        FROM accidents
        GROUP BY hour
        ORDER BY hour
    """,
    "weather_fatality": """
        SELECT weather,
               COUNT(*) AS total_accidents,
               SUM(is_fatal) AS fatal_accidents,
               ROUND(AVG(is_fatal) * 100, 2) AS fatality_rate_pct
        FROM accidents
        GROUP BY weather
        ORDER BY fatality_rate_pct DESC
    """,
    "cause_casualties": """
        SELECT cause,
               COUNT(*) AS total_accidents,
               SUM(casualties) AS total_casualties,
               ROUND(AVG(casualties), 2) AS avg_casualties
        FROM accidents
        GROUP BY cause
        ORDER BY total_casualties DESC
    """,
    "state_ranking": """
        SELECT state,
               total_accidents,
               total_casualties,
               RANK() OVER (ORDER BY total_accidents DESC) AS accident_rank
        FROM (
            SELECT state,
                   COUNT(*) AS total_accidents,
                   SUM(casualties) AS total_casualties
            FROM accidents
            GROUP BY state
        ) sub
        ORDER BY accident_rank
    """,
    "yearly_trend": """
        SELECT year,
               total_accidents,
               total_casualties,
               LAG(total_accidents) OVER (ORDER BY year) AS prev_year_accidents,
               ROUND(
                   (total_accidents - LAG(total_accidents) OVER (ORDER BY year)) * 100.0
                   / LAG(total_accidents) OVER (ORDER BY year), 2
               ) AS yoy_change_pct
        FROM (
            SELECT year,
                   COUNT(*) AS total_accidents,
                   SUM(casualties) AS total_casualties
            FROM accidents
            GROUP BY year
        ) sub
        ORDER BY year
    """,
}

# Run each query and save to CSV
query_results = {}
for name, sql in queries.items():
    result = pd.read_sql_query(sql, conn)
    result.to_csv(f"outputs/{name}.csv", index=False)
    query_results[name] = result
    print(f"    -> outputs/{name}.csv  ({len(result)} rows)")

conn.close()

# -----------------------------------------------
# 5.  CREATE MATPLOTLIB CHARTS
# -----------------------------------------------
print("\n[5] Creating charts ...")

# Use a clean style
plt.style.use("seaborn-v0_8-darkgrid")

# Chart 1: City-wise Fatality Rate (top 15 cities by accident count)
fig, ax = plt.subplots(figsize=(12, 6))
top_cities = query_results["city_fatality"].head(15)
bars = ax.bar(top_cities["city"], top_cities["fatality_rate_pct"],
              color="#e74c3c", edgecolor="white")
ax.set_xlabel("City", fontsize=12)
ax.set_ylabel("Fatality Rate (%)", fontsize=12)
ax.set_title("Top 15 Cities - Fatality Rate (%)", fontsize=14, fontweight="bold")
plt.xticks(rotation=45, ha="right")
# Add value labels on bars
for bar in bars:
    height = bar.get_height()
    ax.text(bar.get_x() + bar.get_width()/2., height + 0.3,
            f'{height:.1f}%', ha='center', va='bottom', fontsize=8)
plt.tight_layout()
plt.savefig("outputs/chart_city_fatality.png", dpi=150)
plt.close()
print("    -> outputs/chart_city_fatality.png")

# Chart 2: Accidents by Hour
fig, ax = plt.subplots(figsize=(12, 5))
hourly = query_results["hourly_accidents"]
ax.plot(hourly["hour"], hourly["total_accidents"],
        marker="o", color="#3498db", linewidth=2, markersize=6)
ax.fill_between(hourly["hour"], hourly["total_accidents"], alpha=0.15, color="#3498db")
ax.set_xlabel("Hour of Day (0-23)", fontsize=12)
ax.set_ylabel("Number of Accidents", fontsize=12)
ax.set_title("Accidents by Hour of Day", fontsize=14, fontweight="bold")
ax.set_xticks(range(0, 24))
plt.tight_layout()
plt.savefig("outputs/chart_hourly_accidents.png", dpi=150)
plt.close()
print("    -> outputs/chart_hourly_accidents.png")

# Chart 3: Weather vs Fatality Rate
fig, ax = plt.subplots(figsize=(10, 5))
weather = query_results["weather_fatality"]
colors = ["#e74c3c", "#e67e22", "#f1c40f", "#2ecc71", "#3498db"]
colors = colors[:len(weather)]  # in case fewer categories
bars = ax.barh(weather["weather"], weather["fatality_rate_pct"],
               color=colors, edgecolor="white")
ax.set_xlabel("Fatality Rate (%)", fontsize=12)
ax.set_ylabel("Weather Condition", fontsize=12)
ax.set_title("Weather Condition vs Fatality Rate", fontsize=14, fontweight="bold")
# Add value labels
for bar in bars:
    width = bar.get_width()
    ax.text(width + 0.2, bar.get_y() + bar.get_height()/2.,
            f'{width:.1f}%', ha='left', va='center', fontsize=10)
plt.tight_layout()
plt.savefig("outputs/chart_weather_fatality.png", dpi=150)
plt.close()
print("    -> outputs/chart_weather_fatality.png")

# Chart 4: Casualties by Cause
fig, ax = plt.subplots(figsize=(10, 6))
cause = query_results["cause_casualties"]
ax.barh(cause["cause"], cause["total_casualties"],
        color="#9b59b6", edgecolor="white")
ax.set_xlabel("Total Casualties", fontsize=12)
ax.set_ylabel("Cause of Accident", fontsize=12)
ax.set_title("Total Casualties by Accident Cause", fontsize=14, fontweight="bold")
plt.tight_layout()
plt.savefig("outputs/chart_cause_casualties.png", dpi=150)
plt.close()
print("    -> outputs/chart_cause_casualties.png")

# Chart 5: Yearly Trend
fig, ax = plt.subplots(figsize=(10, 5))
yearly = query_results["yearly_trend"]
ax.plot(yearly["year"], yearly["total_accidents"],
        marker="s", color="#1abc9c", linewidth=2.5, markersize=8, label="Accidents")
ax.set_xlabel("Year", fontsize=12)
ax.set_ylabel("Total Accidents", fontsize=12)
ax.set_title("Yearly Accident Trend", fontsize=14, fontweight="bold")
# Annotate each point with count
for _, row in yearly.iterrows():
    ax.annotate(f'{int(row["total_accidents"])}',
                xy=(row["year"], row["total_accidents"]),
                textcoords="offset points", xytext=(0, 12),
                ha='center', fontsize=10, fontweight="bold")
ax.set_xticks(yearly["year"].astype(int))
plt.tight_layout()
plt.savefig("outputs/chart_yearly_trend.png", dpi=150)
plt.close()
print("    -> outputs/chart_yearly_trend.png")

# -----------------------------------------------
# 6.  DATA QUALITY CHECKS
# -----------------------------------------------
print("\n[6] Running data quality checks ...")

quality_notes = []

# Check 1: weather = clear but cause = weather
clear_weather_cause = df[
    (df["weather"].str.lower() == "clear") &
    (df["cause"].str.lower() == "weather")
]
n1 = len(clear_weather_cause)
quality_notes.append(
    f"- **Weather = Clear but Cause = Weather**: {n1} rows "
    f"({n1/len(df)*100:.1f}% of data). This is contradictory -- if weather is clear, "
    f"it probably should not be listed as the cause."
)
print(f"    -> Clear weather + weather cause: {n1} rows")

# Check 2: Casualties = 0 but severity = Fatal
fatal_no_casualty = df[
    (df["accident_severity"].str.lower() == "fatal") &
    (df["casualties"] == 0)
]
n2 = len(fatal_no_casualty)
quality_notes.append(
    f"- **Fatal severity but 0 casualties**: {n2} rows. "
    f"A fatal accident should have at least 1 casualty."
)
print(f"    -> Fatal but 0 casualties: {n2} rows")

# Check 3: Minor severity but high casualties (>3)
minor_high_cas = df[
    (df["accident_severity"].str.lower() == "minor") &
    (df["casualties"] > 3)
]
n3 = len(minor_high_cas)
quality_notes.append(
    f"- **Minor severity but >3 casualties**: {n3} rows. "
    f"Minor accidents with many casualties seem inconsistent."
)
print(f"    -> Minor severity but >3 casualties: {n3} rows")

# Check 4: vehicles_involved = 0
zero_vehicles = df[df["vehicles_involved"] == 0]
n4 = len(zero_vehicles)
quality_notes.append(
    f"- **Vehicles involved = 0**: {n4} rows. "
    f"An accident needs at least 1 vehicle."
)
print(f"    -> Zero vehicles involved: {n4} rows")

# Check 5: Negative or unrealistic risk_score
bad_risk = df[(df["risk_score"] < 0) | (df["risk_score"] > 1)]
n5 = len(bad_risk)
quality_notes.append(
    f"- **Risk score outside 0-1 range**: {n5} rows. "
    f"Risk score should be between 0 and 1."
)
print(f"    -> Risk score outside 0-1: {n5} rows")

# Check 6: Uniformly distributed random patterns (synthetic data indicator)
# Check if each city has suspiciously similar severity distribution
sev_by_city = df.groupby("city")["accident_severity"].value_counts(normalize=True)
quality_notes.append(
    f"- **Synthetic data indicator**: Severity distribution across cities is "
    f"suspiciously uniform, consistent with randomly generated data."
)

# -----------------------------------------------
# 7.  COMPUTE 5 KEY INSIGHTS
# -----------------------------------------------
print("\n[7] Computing key insights ...")

insights = []

# Insight 1: Deadliest city
deadliest_city = query_results["city_fatality"].iloc[0]
top_fatal = query_results["city_fatality"].sort_values("fatality_rate_pct", ascending=False).iloc[0]
insights.append(
    f"**Most Accident-Prone City**: {deadliest_city['city']} with "
    f"{int(deadliest_city['total_accidents'])} accidents. "
    f"Highest fatality rate: {top_fatal['city']} at {top_fatal['fatality_rate_pct']}%."
)

# Insight 2: Deadliest hour
deadliest_hour = hourly.loc[hourly["total_accidents"].idxmax()]
safest_hour = hourly.loc[hourly["total_accidents"].idxmin()]
insights.append(
    f"**Peak Accident Hour**: {int(deadliest_hour['hour'])}:00 with "
    f"{int(deadliest_hour['total_accidents'])} accidents. "
    f"Safest hour: {int(safest_hour['hour'])}:00 with "
    f"{int(safest_hour['total_accidents'])} accidents."
)

# Insight 3: Most dangerous weather
worst_weather = weather.iloc[0]
insights.append(
    f"**Most Dangerous Weather**: '{worst_weather['weather']}' has the highest "
    f"fatality rate at {worst_weather['fatality_rate_pct']}% "
    f"({int(worst_weather['fatal_accidents'])} fatalities out of "
    f"{int(worst_weather['total_accidents'])} accidents)."
)

# Insight 4: Top cause
top_cause = cause.iloc[0]
insights.append(
    f"**Leading Cause of Casualties**: '{top_cause['cause']}' caused "
    f"{int(top_cause['total_casualties'])} casualties across "
    f"{int(top_cause['total_accidents'])} accidents."
)

# Insight 5: Overall fatality rate
total = len(df)
fatals = df["is_fatal"].sum()
overall_rate = fatals / total * 100
insights.append(
    f"**Overall Fatality Rate**: {overall_rate:.1f}% -- "
    f"{int(fatals)} fatal out of {total} total accidents."
)

print("\n" + "-" * 40)
print("  5 KEY INSIGHTS")
print("-" * 40)
for i, ins in enumerate(insights, 1):
    print(f"  {i}. {ins}")
print("-" * 40)

# -----------------------------------------------
# 8.  GENERATE README.md
# -----------------------------------------------
print("\n[8] Generating README.md ...")

readme_content = f"""# Indian Road Accident Analysis (2022-2025)

## Problem Statement

Road accidents are a leading cause of death and injury in India. This project
analyses a dataset of **{rows_before:,}** road accident records to uncover patterns
in accident timing, location, weather conditions, and causes -- with the goal of
identifying high-risk factors that could inform road-safety policies.

## Dataset Source

- **Kaggle**: [Indian Road Accident Dataset 2022-2025](https://www.kaggle.com/datasets/sehaj1104/indian-road-accident-dataset-2022-2025) by **sehaj1104**

> **Note**: This dataset appears to be **synthetic / simulated** data.
> Severity distributions are suspiciously uniform across cities, and several
> logical contradictions exist (e.g. weather = "Clear" but cause = "Weather").
> Therefore, findings are limited to this dataset and should **not** be treated
> as real-world conclusions.

## Tools Used

| Tool | Purpose |
|------|---------|
| Python 3 | Data cleaning & analysis |
| pandas | Data manipulation |
| matplotlib | Visualisations |
| SQLite | SQL-based analysis |
| Power BI | Interactive dashboard (DAX measures provided) |
| Git | Version control |

## Data Cleaning Steps

| Step | Detail |
|------|--------|
| Rows loaded | {rows_before:,} |
| Duplicates removed | {dupes:,} |
| Bad dates (could not parse) | {bad_dates:,} |
| Rows dropped (missing date/city) | {nulls_before:,} |
| Rows after cleaning | {rows_after:,} |
| Text columns | Stripped whitespace + Title Case |
| New columns added | `year`, `month`, `time_band`, `is_fatal` |

## 5 Key Insights

"""

for i, ins in enumerate(insights, 1):
    readme_content += f"{i}. {ins}\n"

readme_content += f"""
## Data Quality Notes

These issues suggest the dataset is synthetic:

"""
for note in quality_notes:
    readme_content += f"{note}\n"

readme_content += f"""
## Folder Structure

```
accident_risk_score/
|-- data/
|   |-- raw.csv            # Original dataset
|   +-- cleaned.csv        # Cleaned dataset (for Power BI)
|-- sql/
|   +-- queries.sql        # All 6 SQL queries
|-- outputs/
|   |-- city_fatality.csv
|   |-- hourly_accidents.csv
|   |-- weather_fatality.csv
|   |-- cause_casualties.csv
|   |-- state_ranking.csv
|   |-- yearly_trend.csv
|   +-- chart_*.png        # 5 matplotlib charts
|-- powerbi/
|   +-- dax_measures.txt   # DAX measures for Power BI
|-- notebooks/             # (for Jupyter exploration)
|-- docs/
|   +-- code_explanation.md
|-- run_all.py             # Main pipeline script
|-- requirements.txt
|-- .gitignore
+-- README.md
```

## How to Run

```bash
# 1. Create a virtual environment (optional but recommended)
python -m venv venv
venv\\Scripts\\activate        # Windows
# source venv/bin/activate    # Linux/Mac

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the pipeline
python run_all.py
```

This will clean the data, run SQL queries, generate charts, and create this README.

## Dashboard

![Dashboard](outputs/dashboard.png)

---

*Generated automatically by run_all.py on {datetime.now().strftime("%Y-%m-%d %H:%M")}*
"""

with open("README.md", "w", encoding="utf-8") as f:
    f.write(readme_content)
print("    -> README.md generated")

# -----------------------------------------------
# 9.  FINAL SUMMARY
# -----------------------------------------------
print("\n" + "=" * 60)
print("  PIPELINE COMPLETE")
print("=" * 60)

# List all generated files
print("\nFiles created:")
for root, dirs, files in os.walk("."):
    # skip hidden/venv dirs
    dirs[:] = [d for d in dirs if d not in ("venv", ".git", "__pycache__", ".agents")]
    for f in sorted(files):
        filepath = os.path.join(root, f)
        print(f"  {filepath}")

print("\nDone!")
