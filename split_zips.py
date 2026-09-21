import zipfile
import os

def split_massive_zip(large_zip_name, output_prefix, max_files=50000):
    # Windows hides the .zip extension, but Python needs it explicitly
    if not os.path.exists(large_zip_name):
        print(f"Could not find {large_zip_name}, skipping.")
        return
        
    print(f"Opening {large_zip_name} to split...")
    with zipfile.ZipFile(large_zip_name, 'r') as large_zip:
        all_files = large_zip.namelist()
        
        part_num = 1
        file_count = 0
        current_zip = zipfile.ZipFile(f"{output_prefix}_part{part_num}.zip", 'w', zipfile.ZIP_DEFLATED)
        
        for file in all_files:
            base_name = os.path.basename(file)
            if not base_name.endswith(".txt"): 
                continue
                
            data = large_zip.read(file)
            current_zip.writestr(base_name, data)
            file_count += 1
            
            if file_count >= max_files:
                current_zip.close()
                print(f"Finished {output_prefix}_part{part_num}.zip")
                part_num += 1
                current_zip = zipfile.ZipFile(f"{output_prefix}_part{part_num}.zip", 'w', zipfile.ZIP_DEFLATED)
                file_count = 0
                
        current_zip.close()
        print(f"Finished {output_prefix}_part{part_num}.zip")

split_massive_zip("tournament_results.zip", "tournament_results")
split_massive_zip("tournament_results_50.zip", "tournament_results_50")
split_massive_zip("tournament_results_100.zip", "tournament_results_100")