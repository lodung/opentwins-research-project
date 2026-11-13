import argparse
import csv
from datetime import timedelta
import math
import os
import time

import requests

PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://localhost:30090")
NAMESPACES = {"light": "opentwins-light", "full": "opentwins"}
STEP = 15  # giây giữa hai mốc
STEPS_COUNT = 61  # 0s -> 900s (15 phút)
CONTAINER_FILTER = 'container!="", container!="POD"'


def query_range(promql, start, end):
  res = requests.get(
      f"{PROMETHEUS_URL}/api/v1/query_range",
      params={"query": promql, "start": start, "end": end, "step": f"{STEP}s"},
      timeout=15,
  ).json()
  if res.get("status") != "success":
    raise RuntimeError(f"Lỗi PromQL ({promql}): {res}")
  return res["data"]["result"]


def to_series(result):
  out = {}
  for ts, val in result["values"]:
    v = float(val)
    if not math.isnan(v):
      out[int(ts)] = v
  return out


def pod_series(results):
  return {r["metric"]["pod"]: to_series(r) for r in results}


def build_table(series, names, grid_ts, label):
  rows = []
  last = {name: 0.0 for name in names}
  filled = 0

  for ts in grid_ts:
    row = [ts * 1000]
    for name in names:
      val = series.get(name, {}).get(ts)
      if val is None:
        filled += 1
        val = last[name]
      last[name] = val
      row.append(val)
    rows.append(row)

  if filled:
    print(
        f"   [{label}] {filled}/{len(rows) * len(names)} điểm thiếu,"
        " đã điền bằng giá trị liền trước."
    )
  return rows


def save_csv(filename, header, rows):
  with open(filename, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(header)
    writer.writerows(rows)
  print(f"-> Đã xuất: {filename} ({len(rows)} dòng)")


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument("mode", nargs="?", default="light", choices=NAMESPACES)
  mode = parser.parse_args().mode
  namespace = NAMESPACES[mode]

  # Mốc thời gian chia hết cho STEP để các lần xuất khớp cùng một lưới.
  # Lùi 30s để điểm cuối chắc chắn đã được scrape.
  end_time = ((int(time.time()) - 30) // STEP) * STEP
  start_time = end_time - (STEPS_COUNT - 1) * STEP
  grid_ts = [start_time + i * STEP for i in range(STEPS_COUNT)]

  print(f"=== Xuất dữ liệu | MODE: {mode.upper()} ({namespace}) ===")

  # 1. Chọn selector container. Loại series cgroup cấp Pod (container="") và
  # pause container để không đếm tài nguyên hai lần. Nếu cAdvisor không gắn
  # nhãn container (Docker Desktop) thì loại pause container qua nhãn name.
  # Chỉ cần biết có nhãn hay không nên kiểm tra một mốc end_time là đủ.
  has_container_label = bool(
      query_range(
          f'container_memory_working_set_bytes{{namespace="{namespace}",'
          f" {CONTAINER_FILTER}}}",
          end_time,
          end_time,
      )
  )
  sel = f'namespace="{namespace}", pod!="", ' + (
      CONTAINER_FILTER if has_container_label else 'name!~"k8s_POD_.*"'
  )

  # 2. CPU (% của 1 core) và RAM working set (bytes), cộng dồn theo Pod.
  cpu_res = query_range(
      f"sum(rate(container_cpu_usage_seconds_total{{{sel}}}[1m]))"
      " by (pod) * 100",
      start_time,
      end_time,
  )
  mem_res = query_range(
      f"sum(container_memory_working_set_bytes{{{sel}}}) by (pod)",
      start_time,
      end_time,
  )

  pod_names = sorted({r["metric"]["pod"] for r in mem_res})
  if not pod_names:
    raise RuntimeError(
        f"Không tìm thấy Pod nào đang chạy trong namespace '{namespace}'!"
    )

  # 3. Network (bytes/s). Metric network không có nhãn container do đó dùng
  # selector riêng.
  net_sel = f'namespace="{namespace}", pod!="", interface!="lo"'
  net_res = query_range(
      f"sum(rate(container_network_receive_bytes_total{{{net_sel}}}[1m]) +"
      f" rate(container_network_transmit_bytes_total{{{net_sel}}}[1m]))"
      " by (pod)",
      start_time,
      end_time,
  )

  if net_res:
    net_names = pod_names
    net_series = pod_series(net_res)
  else:
    # cni0 là tổng của cả node: không lọc được theo namespace và không tách
    # được theo Pod, nên chỉ xuất một cột.
    print(
        "CẢNH BÁO: không có network theo Pod (có thể do Docker Desktop ẩn"
        " netns của Pod). Dùng cni0 của cả node, gồm cả traffic ngoài"
        " namespace."
    )
    cni_res = query_range(
        'sum(rate(container_network_receive_bytes_total{interface="cni0"}[1m])'
        ' + rate(container_network_transmit_bytes_total{interface="cni0"}[1m]))',
        start_time,
        end_time,
    )
    net_names = ["cni0_total"]
    net_series = {"cni0_total": to_series(cni_res[0])} if cni_res else {}

  cpu_rows = build_table(pod_series(cpu_res), pod_names, grid_ts, "cpu")
  mem_rows = build_table(pod_series(mem_res), pod_names, grid_ts, "mem")
  net_rows = build_table(net_series, net_names, grid_ts, "network")

  # 4. Xuất CSV theo từng Pod.
  save_csv(f"{mode} cpu.csv", ["Time"] + pod_names, cpu_rows)
  save_csv(f"{mode} mem.csv", ["Time"] + pod_names, mem_rows)
  save_csv(f"{mode} network.csv", ["Time"] + net_names, net_rows)

  # 5. Xuất tổng các Pod theo từng mốc thời gian.
  combined_rows = [
      [
          sum(cpu_rows[i][1:]),  # % core
          sum(mem_rows[i][1:]) / 1e6,  # MB
          sum(net_rows[i][1:]) / 1e6,  # MB/s
          str(timedelta(seconds=i * STEP)),
      ]
      for i in range(STEPS_COUNT)
  ]
  save_csv(
      f"{mode}_combined.csv", ["CPU", "Memory", "Network", "Time"], combined_rows
  )

  # 6. In trung bình toàn cửa sổ.
  avg_cpu = sum(r[0] for r in combined_rows) / STEPS_COUNT
  avg_mem = sum(r[1] for r in combined_rows) / STEPS_COUNT
  avg_net = sum(r[2] for r in combined_rows) / STEPS_COUNT
  print(
      f"\n[{mode.upper()} - {len(pod_names)} Pods] CPU TB: {avg_cpu:.2f}% |"
      f" RAM TB: {avg_mem:.1f} MB | Net TB: {avg_net:.4f} MB/s"
  )


if __name__ == "__main__":
  main()