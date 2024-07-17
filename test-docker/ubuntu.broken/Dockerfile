FROM ubuntu:latest

# install system packages and freecad
RUN apt-get -y update 
RUN apt-get -y install sudo wget

# download freecad appimage
RUN wget https://github.com/FreeCAD/FreeCAD-Bundle/releases/download/0.21.2/FreeCAD_0.21.2-2023-12-17-conda-Linux-x86_64-py310.AppImage -O /usr/local/bin/freecad
RUN chmod 755 /usr/local/bin/freecad

# install freecad dependencies
RUN apt-get -y install python3 python3-pip python3-numpy python3-atomicwrites

# setup Qt gui forwarding 
ENV QT_DEBUG_PLUGINS=1

# setup testuer
RUN useradd testuser
RUN echo "testuser ALL=(ALL) NOPASSWD: ALL" >>/etc/sudoers
