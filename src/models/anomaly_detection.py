import pandas as pd
import matplotlib.pyplot as plt

from sklearn.ensemble import IsolationForest


df = pd.read_csv(
    "data/processed/silver_electricity_market_data.csv"
)

df["timestamp"] = pd.to_datetime(df["timestamp"])

features = [
    "price_eur_mwh",
    "load_mw"
]

X = df[features]

model = IsolationForest(
    contamination=0.01,
    random_state=42
)

df["anomaly"] = model.fit_predict(X)

anomalies = df[df["anomaly"] == -1]

print("\nTotal anomalies detected:")
print(len(anomalies))

print("\nSample anomalies:")
print(
    anomalies[
        ["timestamp", "price_eur_mwh", "load_mw"]
    ].head(10)
)

anomalies.to_csv(
    "data/reports/detected_anomalies.csv",
    index=False
)

plt.figure(figsize=(15, 6))

plt.plot(
    df["timestamp"],
    df["price_eur_mwh"],
    label="Electricity Price"
)

plt.scatter(
    anomalies["timestamp"],
    anomalies["price_eur_mwh"],
    color="red",
    label="Anomaly"
)

plt.title(
    "Electricity Price Anomaly Detection"
)

plt.xlabel("Timestamp")
plt.ylabel("Price (EUR/MWh)")
plt.legend()

plt.tight_layout()

plt.savefig(
    "data/reports/anomaly_detection.png"
)

plt.show()

print("\nSaved:")
print("data/reports/detected_anomalies.csv")
print("data/reports/anomaly_detection.png")