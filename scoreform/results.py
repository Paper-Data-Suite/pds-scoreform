import csv

def export_to_csv(all_results, output_file):
    """Exports structured scoring data to a CSV file.
    
    Includes metadata columns (class_id, assignment_id, student_id) when present
    in the result data.
    """
    if not all_results:
        print("No results to export.")
        return

    # Define the CSV headers - start with Page
    headers = ["Page"]
    
    # Check if any results have metadata; if so, include metadata columns
    has_metadata = any(
        "class_id" in res or "assignment_id" in res or "student_id" in res
        for res in all_results
    )
    
    if has_metadata:
        headers.extend(["class_id", "assignment_id", "student_id"])
    
    # Add score fields
    headers.extend(["Score", "Total"])
    
    # Add question fields
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
                
                # Add metadata if present
                if has_metadata:
                    row["class_id"] = res.get("class_id", "")
                    row["assignment_id"] = res.get("assignment_id", "")
                    row["student_id"] = res.get("student_id", "")
                
                # Add answer details
                for ans in res["answers"]:
                    q_num = ans["Q"]
                    row[f"Q{q_num}"] = ans["Answer"]
                    row[f"Q{q_num}_Correct"] = ans["Correct"]

                writer.writerow(row)

        print(f"Results successfully exported to {output_file}")
    except Exception as e:
        print(f"Error exporting to CSV: {e}")
