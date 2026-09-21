%global modname new-lg4ff

Name:           new-lg4ff-dkms
Version:        0.7.0
Release:        1%{?dist}
Summary:        Improved Logitech steering wheel force feedback driver (DKMS)
License:        GPL-2.0-only
URL:            https://github.com/marthofdoom/new-lg4ff
Source0:        https://github.com/marthofdoom/new-lg4ff/archive/refs/tags/v%{version}.tar.gz
BuildArch:      noarch
Requires:       dkms
Requires(post): dkms
Requires(preun): dkms

%description
Replacement for the in-kernel hid-logitech module for Logitech steering
wheels with a complete force feedback engine and sysfs controls (used by
Oversteer). Built for each kernel through DKMS.

%prep
%autosetup -n %{modname}-%{version}

%install
install -d %{buildroot}/usr/src/%{modname}-%{version}
install -m644 Makefile Kbuild dkms.conf *.c *.h %{buildroot}/usr/src/%{modname}-%{version}/
sed -i 's/^PACKAGE_VERSION=.*/PACKAGE_VERSION="%{version}"/' %{buildroot}/usr/src/%{modname}-%{version}/dkms.conf

%post
dkms add -m %{modname} -v %{version} -q || :
dkms build -m %{modname} -v %{version} -q && dkms install -m %{modname} -v %{version} -q --force || :

%preun
dkms remove -m %{modname} -v %{version} --all -q || :

%files
/usr/src/%{modname}-%{version}

%changelog
* Mon Sep 21 2026 marth <marthofdoom@gmail.com> - 0.7.0-1
- Rumble emulation, ktime effect clock, review fixes.
