FROM python:3.9

# Set the working directory in the container
WORKDIR /usr/src/app/data-to-paper

# Copy the current directory contents into the container at /usr/src/app
COPY . .

# Install necessary libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    libdouble-conversion3 \
    texlive-latex-base \
    texlive-latex-extra \
    texlive-fonts-recommended \
    vim \
    nano \
    pandoc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install -e ./data_to_paper

# Set the default command to run the script
CMD ["python", "data_to_paper/data_to_paper/scripts/run.py"]
