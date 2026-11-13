import json
import pandas as pd
# 1. Đọc dữ liệu từ file kết quả results.json
print("Đang đọc file json...")
with open('edge_time.json', 'r') as f:
    data = json.load(f)
# 2. Trích xuất các trường thông tin và tính độ trễ (latency)
rows = []
for item in data:
    sending_time = item['timestamp']['properties']['value']
    final_time = item['sendingBackTime_Final']
    rows.append({
        'group': item['group']['properties']['value'],
        'rep': item['rep']['properties']['value'],
        'msg': item['msg']['properties']['value'],
        'sendingTime': sending_time,
        'sendingTime_final': final_time,
        'latency_ms': (final_time - sending_time) * 1000
    })
# 3. Xuất ra file CSV
df = pd.DataFrame(rows)
df.to_csv('edge_time_local.csv')
print(f"-> Đã chuyển đổi {len(df)} dòng vào file edge_time_local.csv")