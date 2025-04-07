from setuptools import setup

setup(
    name="battsave",
    version="0.1.0",
    description="A Python service that manages power-monitoring Kasa Smart Plugs to prolong the lifespan of lithium batteries.",
    author="Vlad Pomogaev",
    author_email="vlad.pomogaev@gmail.com",
    url="https://github.com/Arrakark/battsave",
    py_modules=["battsave"],
    install_requires=[
        "python-kasa",
    ],
    entry_points={
        'console_scripts': [
            'battsave=battsave:main',
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "Operating System :: OS Independent",
    ],
)