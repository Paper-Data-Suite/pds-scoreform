import csv

def export_to_csv(all_results, output_file):
    """Exports structured scoring data to a CSV file."""
    if not all_results:
        print("No results to export.")
        return

    # Define the CSV headers
    headers = ["Page", "Score", "Total"]
    for i in range(1, 11):
        headers.append(f"Q{i}")
        headers.append(f"Q{i}_Correct")

    try:
        with open(output_file, mode="w", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=headers)
            writer.writeheader()

            for res in all_results:
                row = {
                    "Page": res["page_num"],
                    "Score": res["score"],
                    "Total": res["total_points"],
                }
                for ans in res["answers"]:
                    q_num = ans["Q"]
                    row[f"Q{q_num}"] = ans["Answer"]
                    row[f"Q{q_num}_Correct"] = ans["Correct"]

                writer.writerow(row)

        print(f"Results successfully exported to {output_file}")
    except Exception as e:
        print(f"Error exporting to CSV: {e}")
