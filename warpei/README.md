## Warpei

This is the repository for the software and hardware used for our OSE4951/EEL4914: Senior Design 1 project. Our project is a low-cost LCD projector that corrects its own image on a curved surface. It projects a grid, measures the distortion with a camera, and pre-warps each frame so the image appears flat. 


## Team

| Member | Major | Area|
| --- | --- | --- |
| Jackson Huff | PSE | Optics, Team Lead |
| Brittany Maragh | PSE | Optics, Calibration Algorithm |
| Arthur Wnuk | EE | Power, Control PCB |
| Christian Artigas | CpE | Software, Firmware |

Advisors: Dr. Chung Yong Chan, Dr. Paul Leisher   
Reviewers: Dr. Stephen Eikenberry, Dr. Di Wu, Dr. Hao Zheng


## Repository Layout

| Folder | Contents |
| --- | --- |
| sbc/ | ROCK 5B application (python): calibration, video warp |
| firmware/ | ESP32 Firmware (C, ESP-IDF): buttons, fans, thermal cutoff|
| protocol/ | UART message definitions shared by sbc/ and firmware/ |
| hardware/ | PCB, power, optics, and mechanical design files |
| testing/ | Test procedures and results |
| docs/ | Diagrams, report figure, meeting notes |


### To Get Started

'''bash  
git lfs install  
git clone https://github.com/Slackadays/seniordesign  
'''   

Git LFS is required. Without it, since CAD files and images are larger, they would download as pointer files. 


## SBC Application (sbc/) [unfinished]

'''bash
cd sbc  
python3 -m venv .venv  
source .venv/bin/activate  
pip install -e .   
pytest  
'''   

Requires python 3.11.


## Firmware (firmware/) [unfinished]

'''bash  
cd firmware  
idf.py set-target esp32  
idf.py build   
idf.py -p <port> flash monitor  

Requires ESP-IDF.


### Application Status
- [ ] Calibration pattern generation
- [ ] Circle detection on saved images
- [ ] Warp solve and RMS validation
- [ ] UART protocol defined
- [ ] MLX90614 driver
- [ ] Video capture and GPU warp on ROCK 5B


## Contributions

- Work on a branch and pull request into 'main'
- Do not commit build output; see '.gitignore'
- Log AI tool prompts and outputs







