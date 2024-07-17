FROM opensuse/tumbleweed:latest

# install system packages
RUN zypper --non-interactive update 
RUN zypper --non-interactive install -t pattern xfce
RUN zypper --non-interactive install python3 python3-pip sudo zsh jupyter jupyter-nbconvert

# install workbench dependencies
RUN zypper --non-interactive install python3-numpy python3-scipy python3-matplotlib python3-atomicwrites freecad

# setup Qt gui forwarding 
#ENV QT_DEBUG_PLUGINS=1

# setup testuer
RUN useradd testuser
RUN echo "testuser ALL=(ALL) NOPASSWD: ALL" >>/etc/sudoers
