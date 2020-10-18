#!/usr/bin/python3

""" Checks a MAME romset against a MAME dat file """
import argparse
import glob
import hashlib
import os
import zipfile
import xml.etree.ElementTree as ET

def parse_args():
    """ Parses command line arguments """
    parser = argparse.ArgumentParser()
    parser.add_argument("-t", "--set-type",
                        help="Type of romset to check",
                        default="nonmerged",
                        choices=("merged", "split", "nonmerged"),
                        type=str)
    parser.add_argument("-d", "--dat",
                        required=True,
                        help="Datfile to use",
                        type=str)
    parser.add_argument("rom_dir", help="Directory where you roms are stored",
                        type=str)
    args = parser.parse_args()
    return args

def get_game_romset(game):
    """ Get a romset from an XML blurb """
    romset = dict()

    for attr in ('name', 'cloneof', 'romof'):
        if attr in game.attrib:
            romset[attr] = game.get(attr)

    romset['rom_digests'] = dict()
    for rom in game.findall('rom'):
        romset['rom_digests'][rom.get('name')] = rom.get('sha1')

    return romset

def create_romfile_map(datfile_name):
    """ Parses a datfile and creates a maps of the roms found in it.
        Returns a dictionary of all the roms found in the mapfile
        indexed by rom name """
    rom_map = dict()
    root = ET.parse(datfile_name).getroot()
    for game in root.findall('game'):
        romset = get_game_romset(game)
        rom_map[romset['name']] = romset
    return rom_map

def get_zip_member_digests(zipfile_name):
    """ Opens a zip file and returns a sha1 digest
        of all the members of the zip """
    digests = dict()

    zip_archive = zipfile.ZipFile(zipfile_name)
    for member in zip_archive.namelist():
        with zip_archive.open(member) as member_file:
            member_content = member_file.read()
        sha1_digest = hashlib.sha1(member_content).hexdigest()
        digests[member] = sha1_digest
    zip_archive.close()

    return digests

def create_romfile_checklist(rom_map, set_type):
    """ Creates a dict of roms to check by modifying the rom map
        in-place depending on the set-type:
           - nonmerged: each game zip file contains all the ROMS for the game
                -> do nothing, the map is what we need to test against
           - merged: the parent zip file contains all the ROMS for the parent and its clones.
                -> move all the clones ROMs to their parent, then delete the clone from the map
           - split: the clone zip file contains only the files needed on top of the parent.
                -> delete all the parent ROMS references from the clone
    """
    if set_type == "nonmerged":
        return

    if set_type == "merged":
        delete_list = list()
        for zip_name, romset in rom_map.items():
            if 'cloneof' in romset:
                parent_name = romset['cloneof']
                parent_romset = rom_map[parent_name] # TODO: check for errors !
                for rom_name, rom_digest in romset['rom_digests'].items():
                    if rom_name not in parent_romset['rom_digests']:
                        parent_romset['rom_digests'][rom_name] = rom_digest
                    else:
                        pass # TODO: coherency check. Both roms should have the same digest
                delete_list.append(zip_name)
        for zip_name in delete_list:
            del rom_map[zip_name]
        return

    if set_type == "split":
        for zip_name, romset in rom_map.items():
            if 'cloneof' in romset:
                parent_name = romset['cloneof']
                parent_romset = rom_map[parent_name]
                for rom_name, rom_digest in parent_romset['rom_digests'].items():
                    if rom_name in romset['rom_digests']:
                        del romset['rom_digests'][rom_name]
        return

def check_roms(rom_map, rom_dir):
    """ Check roms in rompath """
    missing_files = list()
    ok_files = list()
    missing_roms = list()
    bad_roms = list()

    cur_rom = 1
    num_roms = len(rom_map)

    print("Starting check. %d files in datfile" % (num_roms))
    zip_list = glob.glob(os.path.join(rom_dir, '*.zip'))

    for zip_name in rom_map:
        if cur_rom % 128 == 0:
            print("%d/%d" % (cur_rom, num_roms))
        zip_file = os.path.join(rom_dir, zip_name) + ".zip"
        if zip_file in zip_list:
            zip_digests = get_zip_member_digests(zip_file)
            map_digests = rom_map[zip_name]['rom_digests']
            zip_ok = True
            for rom_name, digest in zip_digests.items():
                if rom_name not in map_digests:
                    missing_roms.append(zip_name + "/" + rom_name)
                    zip_ok = False
                elif digest != map_digests[rom_name]:
                    bad_roms.append(zip_name + "/" + rom_name)
                    zip_ok = False
            if zip_ok:
                ok_files.append(zip_file)
        else:
            missing_files.append(zip_name)
        cur_rom += 1

    print("zip ok: %d\nbad roms: %d\nmissing roms: %d\nmissing_files: %d" %
          (len(ok_files), len(bad_roms), len(missing_roms), len(missing_files)))
    print("bad roms:", bad_roms)
    print("missing roms:", missing_roms)
    print("missing files:", missing_files)

ARGS = parse_args()
ROM_MAP = create_romfile_map(ARGS.dat)
create_romfile_checklist(ROM_MAP, ARGS.set_type)
check_roms(ROM_MAP, ARGS.rom_dir)
