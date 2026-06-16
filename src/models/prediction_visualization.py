import os
import pandas as pd
import joblib
import matplotlib.pyplot as plt

DATA_PATH = "data/features/gold_model_features.csv"
MODEL_PATH = "artifacts/models/best_gold_model.joblib"
FEATURES_PATH = "artifacts/models/gold_model_features.joblib"
OUTPUT_PATH = "data/reports/actual_vs_predicted.png"

os.makedirs("data/reports", exist_ok=True)

df = pd.read_csv(DATA_PATH)
df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
df = df.sort_values("timestamp")

model = joblib.load(MODEL_PATH)
features = joblib.load(FEATURES_PATH)

target = "target_price_next_hour"

X = df[features]
y = df[target]

split_index = int(len(df) * 0.8)

X_test = X.iloc[split_index:]
y_test = y.iloc[split_index:]
timestamps = df["timestamp"].iloc[split_index:]

predictions = model.predict(X_test)

results = pd.DataFrame({
    "timestamp": timestamps,
    "actual_price": y_test,
    "predicted_price": predictions
})

results.to_csv("data/reports/actual_vs_predicted.csv", index=False)

plot_data = results.tail(500)

plt.figure(figsize=(14, 6))
plt.plot(plot_data["timestamp"], plot_data["actual_price"], label="Actual Price")
plt.plot(plot_data["timestamp"], plot_data["predicted_price"], label="Predicted Price")

plt.xlabel("Timestamp")
plt.ylabel("Electricity Price (EUR/MWh)")
plt.title("Actual vs Predicted Electricity Prices")
plt.legend()
plt.tight_layout()

plt.savefig(OUTPUT_PATH)
plt.show()

print("Saved prediction results to data/reports/actual_vs_predicted.csv")
print("Saved plot to data/reports/actual_vs_predicted.png")
print(results.tail())