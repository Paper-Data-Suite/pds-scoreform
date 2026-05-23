import csv
import os


def export_to_csv(all_results, output_file):
    """Exports structured scoring data to a CSV file.
    
    Includes metadata columns (class_id, assignment_id, student_id) when present
    in the result data.
    
    Returns True on success, False on failure.
    """
    if not all_results:
        print("No results to export.")
        return False

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
        return True
    except Exception as e:
        print(f"Error exporting to CSV: {e}")
        return False


def export_routed_results(all_results):
    """Route and export QR-aware scoring results to their assignment folders.
    
    Groups results by (class_id, assignment_id) and writes each group to:
        classes/<class_id>/assignments/<assignment_id>/results.csv
    
    Returns True on success, False on failure.
    """
    if not all_results:
        print("No results to export.")
        return False

    # Validate that all results have required metadata
    for res in all_results:
        if "class_id" not in res or "assignment_id" not in res:
            print(
                f"Error: Result missing required metadata. "
                f"class_id={res.get('class_id')}, assignment_id={res.get('assignment_id')}"
            )
            return False

    # Group results by (class_id, assignment_id)
    groups = {}
    for res in all_results:
        key = (res["class_id"], res["assignment_id"])
        if key not in groups:
            groups[key] = []
        groups[key].append(res)

    # Write each group to its assignment folder
    all_success = True
    for (class_id, assignment_id), results in groups.items():
        output_dir = os.path.join("classes", class_id, "assignments", assignment_id)
        
        if not os.path.exists(output_dir):
            print(f"Error: Assignment directory does not exist: {output_dir}")
            all_success = False
            continue
        
        output_file = os.path.join(output_dir, "results.csv")
        
        # Define the CSV headers - start with Page
        headers = ["Page", "class_id", "assignment_id", "student_id", "Score", "Total"]
        
        # Add question fields
        for i in range(1, 11):
            headers.append(f"Q{i}")
            headers.append(f"Q{i}_Correct")

        try:
            with open(output_file, mode="w", newline="", encoding="utf-8") as csv_file:
                writer = csv.DictWriter(csv_file, fieldnames=headers)
                writer.writeheader()

                for res in results:
                    row = {
                        "Page": res["page_num"],
                        "class_id": res.get("class_id", ""),
                        "assignment_id": res.get("assignment_id", ""),
                        "student_id": res.get("student_id", ""),
                        "Score": res["score"],
                        "Total": res["total_points"],
                    }
                    
                    # Add answer details
                    for ans in res["answers"]:
                        q_num = ans["Q"]
                        row[f"Q{q_num}"] = ans["Answer"]
                        row[f"Q{q_num}_Correct"] = ans["Correct"]

                    writer.writerow(row)

            print(f"Results routed to {output_file}")
        except Exception as e:
            print(f"Error writing routed results to {output_file}: {e}")
            all_success = False

    return all_success
