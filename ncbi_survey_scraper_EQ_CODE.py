#!/usr/bin/env python3
"""
BIN601 Final Project: American Gut NCBI BioSample Survey Scraper

"""

# Import the libraries needed to run the scraper
import argparse  # Allows the user to enter options when running the script
import random    # Randomly selects BioSample IDs
import re        # Searches for BioSample accession numbers
import sys       # Allows the script to exit with an error code
import time      # Adds a pause between webpage requests
from pathlib import Path  # Makes it easier to work with file and folder paths

import pandas as pd  # Organizes survey data and exports CSV files
import requests      # Connects to NCBI webpages
from lxml import html  # Reads and extracts information from webpage HTML


# Identify the common accession number formats used by NCBI BioSample
BIOSAMPLE_PATTERN = re.compile(
    r"\b(?:SAMEA|SAMN|SAMD)\d+\b",
    re.IGNORECASE
)


# List the four survey categories that will be used to create filtered CSVs
# and plots. The script checks for these question names on the NCBI pages.
PLOT_CATEGORIES = {
    "sex": ["sex", "gender"],
    "vitamin_d_supplement_frequency": [
        "vitamin_d_supplement_frequency",
        "vitamin d supplement frequency"
    ],
    "weight_kg": ["weight_kg", "weight kg"],
    "weight_change": ["weight_change", "weight change"],
}


# Create a function to standardize survey question names.
def normalize_question(question):
    return re.sub(r"[^a-z0-9]+", "", str(question).casefold())


# Create a function to read the input text file and collect BioSample IDs.
def read_biosample_ids(input_file):

    # Check that the input file exists before trying to read it.
    input_path = Path(input_file)
    if not input_path.is_file():
        raise FileNotFoundError(f"Input file was not found: {input_path}")

    # Read the contents of the text file.
    text = input_path.read_text(encoding="utf-8", errors="replace")

    # Search the file for all BioSample accession numbers.
    found_ids = BIOSAMPLE_PATTERN.findall(text)

    # Remove duplicate IDs while keeping their original order.
    unique_ids = list(dict.fromkeys(item.upper() for item in found_ids))

    # Check that at least one valid BioSample ID was found.
    if not unique_ids:
        raise ValueError(
            "No BioSample accession numbers were found. "
            "Expected IDs such as SAMEA123456, SAMN123456, or SAMD123456."
        )

    # Return the list of unique BioSample IDs.
    return unique_ids


# Create a function to divide the original BioSample ID list into
# four smaller text files. These files can be used as example inputs.
def split_ids_into_four(ids, output_folder):

    # Create the output folder if it does not already exist.
    output_folder.mkdir(parents=True, exist_ok=True)

    # Calculate how many IDs should go into each of the four files.
    # The remainder is distributed among the first files.
    base_size, remainder = divmod(len(ids), 4)

    # Keep track of where each group of IDs starts.
    start = 0

    # Store the names of the four files that are created.
    created_files = []

    # Loop four times to create four separate input files.
    for index in range(4):

        # Calculate the number of IDs for the current file.
        chunk_size = base_size + (1 if index < remainder else 0)

        # Select the IDs that belong in this file.
        chunk = ids[start:start + chunk_size]
        start += chunk_size

        # Create a filename for the current group of IDs.
        output_file = output_folder / f"biosample input {index + 1}.txt"

        # Write the selected BioSample IDs into the text file.
        output_file.write_text("\n".join(chunk) + "\n", encoding="utf-8")

        # Save the filename and print how many IDs it contains.
        created_files.append(output_file)
        print(f"Created {output_file} ({len(chunk)} IDs)")

    # Return the list of created input files.
    return created_files


# Create a function that visits one NCBI BioSample webpage
# and scrapes the survey questions and their corresponding answers.
def scrape_biosample(sample_id, session):

    # Build the NCBI webpage URL using the current BioSample ID.
    url = f"https://www.ncbi.nlm.nih.gov/biosample/{sample_id}"

    # Request the webpage and check whether the request was successful.
    try:
        response = session.get(url, timeout=25)
        response.raise_for_status()

    # If the webpage cannot be accessed, print an error and move on.
    except requests.RequestException as error:
        print(f"Could not access {sample_id}: {error}")
        return []

    # Convert the webpage HTML into a format that can be searched.
    try:
        page = html.fromstring(response.content)

    # If the webpage cannot be read, print an error and move on.
    except (ValueError, TypeError) as error:
        print(f"Could not parse webpage for {sample_id}: {error}")
        return []

    # Create an empty list to store the survey responses for this BioSample.
    records = []

    # Search the webpage for all rows inside HTML tables.
    for row in page.xpath("//table//tr"):

        # Extract the individual cells from each table row.
        cells = row.xpath("./th | ./td")

        # Skip rows that do not contain at least two cells.
        if len(cells) < 2:
            continue

        # Extract the survey question from the first cell.
        question = re.sub(
            r"\s+", " ", cells[0].text_content()
        ).strip()

        # Extract the answer from the remaining cells.
        answer = " ".join(
            cell.text_content().strip() for cell in cells[1:]
        )

        # Remove extra spaces from the answer.
        answer = re.sub(r"\s+", " ", answer).strip()

        # Only save rows that contain both a question and an answer.
        if question and answer:
            records.append({
                "BioSample_ID": sample_id,
                "Question": question,
                "Answer": answer,
            })

    # Print a message if no survey responses were found for this ID.
    if not records:
        print(f"No survey table responses found for {sample_id}.")

    # Return all the question and answer records for this BioSample.
    return records


# Create a function to find a survey question that matches one of
# the four categories listed in PLOT_CATEGORIES.
def find_question(available_questions, aliases):

    # Standardize all question names so they can be compared more easily.
    normalized_questions = {
        normalize_question(question): question
        for question in available_questions
    }

    # First, look for an exact match between the question and category name.
    for alias in aliases:
        key = normalize_question(alias)
        if key in normalized_questions:
            return normalized_questions[key]

    # If an exact match is not found, look for a question that contains
    # the category name or one of its alternative names.
    for alias in aliases:
        key = normalize_question(alias)
        if len(key) >= 5:
            for normalized, original in normalized_questions.items():
                if key in normalized:
                    return original

    # Return None if no matching question was found.
    return None


# Create a function to generate a plot for one survey category.
def make_category_plot(data, question, category_name, output_folder):

    # Import the plotting library when a plot is requested.
    try:
        import matplotlib.pyplot as plt

    # Display an error message if matplotlib is not installed.
    except ImportError:
        print("Plots skipped. Install matplotlib with: pip install matplotlib")
        return False

    # Collect the survey answers and remove missing or empty responses.
    answers = data["Answer"].dropna().astype(str).str.strip()
    answers = answers[answers != ""]

    # Skip the plot if there are no answers to display.
    if answers.empty:
        print(f"No non-empty answers available for {question}; plot skipped.")
        return False

    # Create the folder where the plots will be saved.
    output_folder.mkdir(parents=True, exist_ok=True)

    # Try to convert the survey answers into numbers.
    numeric_answers = pd.to_numeric(
        answers.str.replace(",", "", regex=False),
        errors="coerce"
    )

    # Calculate the percentage of answers that were successfully converted.
    numeric_fraction = numeric_answers.notna().mean()

    # Create the figure and axes for the plot.
    figure, axis = plt.subplots(figsize=(10, 6))

    # For weight in kilograms, create a histogram if most answers are numeric.
    if category_name == "weight_kg" and numeric_fraction >= 0.5:
        values = numeric_answers.dropna()
        axis.hist(values, bins="auto")
        axis.set_xlabel("Reported weight")
        axis.set_ylabel("Number of BioSamples")

    # For other categories, create a bar plot showing response frequencies.
    else:
        counts = answers.value_counts().head(25)
        counts.plot(kind="bar", ax=axis)
        axis.set_xlabel("Survey response")
        axis.set_ylabel("Number of BioSamples")
        axis.tick_params(axis="x", labelrotation=45)

    # Add a title and adjust the layout so labels fit.
    axis.set_title(f"{category_name.replace('_', ' ').title()}: {question}")
    figure.tight_layout()

    # Save the plot as a PNG file in the output folder.
    plot_file = output_folder / f"{category_name}.png"
    figure.savefig(plot_file, dpi=300, bbox_inches="tight")

    # Close the figure after saving it.
    plt.close(figure)

    print(f"Plot saved to: {plot_file}")

    # Return True to indicate that the plot was successfully created.
    return True


# Main function: controls the order in which the entire project runs.
def main():

    # Set up the command-line arguments that the user can provide.
    parser = argparse.ArgumentParser(
        description=(
            "Scrape American Gut BioSample survey data and create four "
            "category-specific CSV files and plots."
        )
    )

    # Ask the user to provide the name of the input text file.
    parser.add_argument(
        "input_file",
        help="Original text file containing NCBI BioSample IDs."
    )

    # Set the number of BioSample IDs to randomly scrape.
    # The default is 200. Enter 0 to scrape every ID in the file.
    parser.add_argument(
        "--sample-size",
        type=int,
        default=200,
        help=(
            "Number of IDs to randomly scrape (default: 200). "
            "Use 0 to scrape all IDs."
        )
    )

    # Set the folder where the CSV files and plots will be saved.
    parser.add_argument(
        "--output-dir",
        default="output",
        help="Folder for CSV and graph outputs (default: output)."
    )

    # Set the folder where the four example input files will be saved.
    parser.add_argument(
        "--split-dir",
        default="example_inputs",
        help="Folder for the four split text files (default: example_inputs)."
    )

    # Add an optional command that tells the script to create plots.
    parser.add_argument(
        "--plot",
        action="store_true",
        help="Create plots for the four categories when matching questions exist."
    )

    # Set the number of seconds to wait between webpage requests.
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Seconds to wait between webpage requests (default: 1)."
    )

    # Set a random seed so the same sample can be selected again.
    parser.add_argument(
        "--seed",
        type=int,
        default=31,
        help="Random seed for repeatable subset selection (default: 31)."
    )

    # Read the command-line arguments entered by the user.
    args = parser.parse_args()

    # Check that the sample size and request delay are not negative.
    if args.sample_size < 0:
        parser.error("--sample-size must be zero or greater.")
    if args.delay < 0:
        parser.error("--delay must be zero or greater.")

    # Read the BioSample IDs from the input file.
    # If the file is missing or contains no valid IDs, display an error.
    try:
        all_ids = read_biosample_ids(args.input_file)
    except (FileNotFoundError, ValueError) as error:
        print(f"Error: {error}")
        return 1

    # Display the total number of unique BioSample IDs found.
    print(f"Found {len(all_ids)} unique BioSample IDs in {args.input_file}.")

    # Divide the complete list of IDs into four example input files.
    split_ids_into_four(all_ids, Path(args.split_dir))

    # Randomly select the number of IDs requested by the user.
    # By default, 200 IDs are selected. Use --sample-size 0 for all IDs.
    if args.sample_size == 0:
        selected_ids = all_ids.copy()
        print(f"Scraping all {len(selected_ids)} BioSample IDs.")

    else:
        # Do not try to select more IDs than are available in the input file.
        sample_count = min(args.sample_size, len(all_ids))

        # Use the random seed to select a repeatable group of unique IDs.
        rng = random.Random(args.seed)
        selected_ids = rng.sample(all_ids, sample_count)

        print(
            f"Randomly selected {len(selected_ids)} of {len(all_ids)} "
            "BioSample IDs for scraping."
        )

    # Create an empty list to store all survey responses.
    all_records = []

    # Keep track of how many BioSamples returned survey data.
    successful_samples = 0

    # Open a requests session to reuse the connection while scraping.
    with requests.Session() as session:

        # Identify the script when sending requests to NCBI.
        session.headers.update({
            "User-Agent": (
                "BIN601-American-Gut-BioSample-Scraper/1.0 "
                "(educational project)"
            )
        })

        # Loop through each selected BioSample ID and scrape its webpage.
        for number, sample_id in enumerate(selected_ids, start=1):

            # Print the current progress of the scraping process.
            print(f"[{number}/{len(selected_ids)}] Scraping {sample_id}...")

            # Scrape the current BioSample and collect its survey responses.
            sample_records = scrape_biosample(sample_id, session)

            # If responses were found, add them to the complete results list.
            if sample_records:
                successful_samples += 1
                all_records.extend(sample_records)

            # Pause before requesting the next webpage.
            if number < len(selected_ids):
                time.sleep(args.delay)

    # Stop the script if no survey responses were collected.
    if not all_records:
        print("No survey responses were collected. No output CSV was created.")
        return 1

    # Create the main output folder if it does not already exist.
    output_folder = Path(args.output_dir)
    output_folder.mkdir(parents=True, exist_ok=True)

    # Set the location for the folder that will contain the plots.
    plots_folder = output_folder / "plots"

    # Convert all collected survey responses into a pandas DataFrame.
    all_data = pd.DataFrame(all_records)

    # Export the complete scraped survey dataset as a CSV file.
    all_data_file = output_folder / "all_biosample_survey_results.csv"
    all_data.to_csv(all_data_file, index=False)
    print(f"\nAll scraped data saved to: {all_data_file}")

    # Create a sorted list of all survey questions found in the dataset.
    available_questions = sorted(
        all_data["Question"].dropna().unique(),
        key=str.casefold
    )

    # Search the collected questions for the four categories of interest.
    print("\nMatching survey questions for the four plot categories:")
    plots_created = 0

    # Loop through each category and its possible question names.
    for category_name, aliases in PLOT_CATEGORIES.items():

        # Find the actual survey question that matches the current category.
        question = find_question(available_questions, aliases)

        # If no matching question exists, display a message and move on.
        if question is None:
            print(
                f"  {category_name}: no matching question found. "
                f"Looked for: {', '.join(aliases)}"
            )
            continue

        # Filter the complete dataset to include only responses
        # that belong to the current survey question.
        category_data = all_data.loc[
            all_data["Question"].map(normalize_question)
            == normalize_question(question),
            ["BioSample_ID", "Question", "Answer"],
        ].copy()

        # Save the filtered responses as a separate CSV file.
        category_csv = output_folder / f"{category_name}.csv"
        category_data.to_csv(category_csv, index=False)

        print(
            f"  {category_name}: matched '{question}' "
            f"({len(category_data)} responses); saved {category_csv}"
        )

        # If the user included --plot, create a plot for this category.
        if args.plot:
            if make_category_plot(
                category_data,
                question,
                category_name,
                plots_folder
            ):
                plots_created += 1

    # Print a summary after the scraping and exporting are complete.
    print("\nScraping complete!")
    print(f"IDs in original file: {len(all_ids)}")
    print(f"IDs selected for scraping: {len(selected_ids)}")
    print(f"BioSamples with survey data: {successful_samples}")
    print(f"All scraped records: {len(all_data)}")
    print(f"Category plots created: {plots_created}")
    print(f"Output folder: {output_folder}")

    # Let the user know if fewer than four plots were created.
    if args.plot and plots_created < 4:
        print(
            "Some plots were not created because the matching survey "
            "question was not present in the scraped data."
        )

    # Return 0 to indicate that the script finished successfully.
    return 0


# Run the main function when this file is executed directly.
# This prevents the script from running automatically if it is imported
# into another Python file.
if __name__ == "__main__":
    sys.exit(main())
