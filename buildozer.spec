[app]
title = SOS Deployer
package.name = sosdeployer
package.domain = org.sos
source.dir = .
source.include_exts = py,png,jpg,kv,atlas
version = 0.2

requirements = hostpython3==3.11.5,python3==3.11.5,kivy==2.3.0,requests,eth-account==0.12.3,eth-abi==4.2.1,eth-utils==2.3.1,eth-keys==0.4.0,eth-rlp==2.1.0,eth-typing==3.5.2,eth-hash==0.5.2,eth-keyfile==0.8.1,hexbytes==1.2.1,bitarray==2.8.1,rlp==3.0.0,pycryptodome==3.19.0,parsimonious==0.10.0,regex==2023.10.3,toolz==0.12.0,pyrsistent==0.19.3,attrs==23.1.0,cffi,pycparser,ckzg==1.0.2,pydantic==2.5.3

orientation = portrait
android.permissions = INTERNET
android.api = 33
android.minapi = 24
android.ndk = 25b
android.ndk_api = 24
android.archs = arm64-v8a
android.accept_sdk_license = True
android.allow_backup = True

[buildozer]
log_level = 2
