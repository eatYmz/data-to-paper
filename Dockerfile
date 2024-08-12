FROM python:3.9

# Set the working directory in the container
WORKDIR /usr/src/app/data-to-paper

# Copy the current directory contents into the container at /usr/src/app
COPY . .

# Install necessary libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    libdouble-conversion3 \
    libegl1 \
    libgl1-mesa-glx \
    libxkbcommon0 \
    libdbus-1-3 \
    libxcb1 \
    libxcb-cursor0 \
    libx11-xcb1 \
    libxrender1 \
    libxi6 \
    libxcomposite1 \
    libxcursor1 \
    libxrandr2 \
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
