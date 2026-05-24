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
    # Check if any results include source_file
    has_source = any("source_file" in res for res in all_results)
    
    if has_metadata:
        headers.extend(["class_id", "assignment_id", "student_id"])
    if has_source:
        headers.append("source_file")
    
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
                # Add source file if present
                if has_source:
                    row["source_file"] = res.get("source_file", "")
                
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


def _enrich_results_with_roster(all_results):
    """Attach roster-derived fields to results in place.

    Adds `last_name`, `first_name`, and `period` to each result dict when possible.
    Returns True if at least one roster was successfully loaded, False otherwise.
    """
    if not all_results:
        return False

    # Group results by class_id for efficient roster loading
    by_class = {}
    for res in all_results:
        class_id = res.get("class_id")
        if not class_id:
            print(f"Warning: result missing class_id for page {res.get('page_num')}")
            # Ensure fields exist
            res.setdefault("last_name", "")
            res.setdefault("first_name", "")
            res.setdefault("period", "")
            continue
        by_class.setdefault(class_id, []).append(res)

    any_loaded = False

    for class_id, results in by_class.items():
        roster_path = os.path.join("classes", class_id, "roster.csv")

        # Import locally to avoid circular imports
        try:
            from scoreform.roster import load_roster
        except Exception:
            print("Warning: Could not import load_roster from scoreform.roster")
            # Leave fields blank
            for r in results:
                r.setdefault("last_name", "")
                r.setdefault("first_name", "")
                r.setdefault("period", "")
            continue

        if not os.path.exists(roster_path):
            print(f"Warning: Roster file not found for class '{class_id}': {roster_path}")
            for r in results:
                r.setdefault("last_name", "")
                r.setdefault("first_name", "")
                r.setdefault("period", "")
            continue

        roster = load_roster(roster_path)
        if roster is None:
            print(f"Warning: Failed to load roster for class '{class_id}': {roster_path}")
            for r in results:
                r.setdefault("last_name", "")
                r.setdefault("first_name", "")
                r.setdefault("period", "")
            continue

        any_loaded = True

        # Build lookup by student_id
        lookup = {s["student_id"]: s for s in roster.get("students", [])}

        for r in results:
            sid = r.get("student_id", "")
            student = lookup.get(sid)
            if student:
                r["last_name"] = student.get("last_name", "")
                r["first_name"] = student.get("first_name", "")
                r["period"] = student.get("period", "")
            else:
                print(f"Warning: student_id '{sid}' not found in roster {roster_path}")
                r.setdefault("last_name", "")
                r.setdefault("first_name", "")
                r.setdefault("period", "")

    return any_loaded


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

    # Enrich results with roster metadata (last_name, first_name, period)
    enriched_ok = _enrich_results_with_roster(all_results)
    if not enriched_ok:
        # Continue exporting even if some roster lookups failed; warnings printed by helper
        pass

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
        headers = [
            "Page",
            "class_id",
            "assignment_id",
            "student_id",
            "last_name",
            "first_name",
            "period",
            "source_file",
            "Score",
            "Total",
        ]
        
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
                        "last_name": res.get("last_name", ""),
                        "first_name": res.get("first_name", ""),
                        "period": res.get("period", ""),
                        "source_file": res.get("source_file", ""),
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
