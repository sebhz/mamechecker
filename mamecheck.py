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
    parser.add_argument("-d", "--dat",
                        required=True,
                        help="Datfile to use",
                        type=str)
    parser.add_argument("-t", "--set-type",
                        help="Type of romset to check",
                        default="nonmerged",
                        choices=("merged", "split", "nonmerged"),
                        type=str)
    parser.add_argument("rom_dir", help="Directory where you roms are stored",
                        type=str)
    args = parser.parse_args()

    return args

def get_game_romset(game):
    """ Get a romset from an XML blurb """
    romset = dict()

    for attr in game.attrib:
        romset[attr] = game.get(attr)

    romset['rom_digests'] = dict()
    for rom in game.findall('rom'):
        if 'sha1' in rom.attrib: # No sha1 possible in case of bad dump
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

def create_merged_checklist(rom_map):
    """ Creates a dict of roms to check by modifying the rom map
        in-place depending on the set-type
        Merged roms: the parent zip file contains all the ROMS
        for the parent and its clones.
            -> Move all the clones ROMs to their parent, then delete the
               clone from the map
    """
    delete_list = list()
    for cur_name, cur_romset in rom_map.items():
        if 'romof' not in cur_romset:
            continue
        parent_name = cur_romset['romof']
        if parent_name in rom_map:
            parent_romset = rom_map[parent_name]
            if 'isbios' in parent_romset:
                continue
            for cur_rom_name, cur_rom_digest in cur_romset['rom_digests'].items():
                if cur_rom_name not in parent_romset['rom_digests']:
                    parent_romset['rom_digests'][cur_rom_name] = cur_rom_digest
                elif parent_romset['rom_digests'][cur_rom_name] != cur_rom_digest:
                    print("Incoherency between parent (%s) and clone (%s) ROM digest (%s)" %
                          (parent_name, cur_name, cur_rom_name))
            delete_list.append(cur_name)
        else:
            print("romset %s is marked as clone of romset %s, but %s is not found" %
                  (cur_name, parent_name, parent_name))
    for cur_name in delete_list:
        del rom_map[cur_name]

def create_split_checklist(rom_map):
    """ Creates a dict of roms to check by modifying the rom map
        in-place depending on the set-type
        Split roms: the clone zip file contains only the files needed
        on top of the parent.
           -> delete all the parent ROMS references from the clone
    """
    for cur_name, cur_romset in rom_map.items():
        if 'romof' not in cur_romset:
            continue
        parent_name = cur_romset['romof']
        if parent_name in rom_map:
            parent_romset = rom_map[parent_name]
            for parent_rom_name, parent_rom_digest in parent_romset['rom_digests'].items():
                if parent_rom_name in cur_romset['rom_digests']:
                    if cur_romset['rom_digests'][parent_rom_name] != parent_rom_digest:
                        print("Incoherency between parent (%s) and clone (%s) ROM digest (%s)" %
                              (parent_name, cur_name, parent_rom_name))
                    del cur_romset['rom_digests'][parent_rom_name]
        else:
            print("romset %s is marked as clone of romset %s, but %s is not found" %
                  (cur_name, parent_name, parent_name))

def create_romfile_checklist(rom_map, set_type):
    """ Creates a dict of roms to check by modifying the rom map
        in-place depending on the set-type
        Nonmerged roms: each game zip file contains all the ROMS for the game
            -> do nothing, the map is what we need to test against
    """
    if set_type == "merged":
        create_merged_checklist(rom_map)

    if set_type == "split":
        create_split_checklist(rom_map)

def display_stats(stats):
    """ Display statistics """
    print("""
-- Summary of database --
%d romsets missing (zip not found in romdir)
%d bad romsets (zip found in romdir, but containing corrupted or missing roms)

%d missing roms (needed rom not found in its zip file)
%d bad roms (rom is found in its zip file, but has wrong digest)
""" % (len(stats['missing_files']),
       len(stats['bad_files']),
       sum([len(v) for v in stats['missing_roms'].values()]),
       sum([len(v) for v in stats['bad_roms'].values()])))

    print("Missing files list")
    for zip_file in stats['missing_files']:
        print("\t-", os.path.basename(zip_file) + ".zip")

    print("Bad files list")
    for zip_file in stats['bad_files']:
        print("\t-", os.path.basename(zip_file) + ".zip")

    print("Missing ROMS list")
    for zip_file, roms_list in stats['missing_roms'].items():
        print("\t-", zip_file + ".zip")
        for rom_name in roms_list:
            print("\t\t-", rom_name)

    print("Bad ROMS list (rom, expected digest, obtained digest)")
    for zip_file, roms_list in stats['bad_roms'].items():
        print("\t-", zip_file + ".zip")
        for rom_desc in roms_list:
            print("\t\t-", rom_desc)

def check_roms(rom_map, rom_dir):
    """ Check roms in rompath """
    stats = {'missing_files': list(), # romset not found
             'bad_files': set(),     # romset found but contains corrupted or missing roms
             'missing_roms': dict(),  # roms missing (format romset: (rom1, rom2,...))
             'bad_roms': dict()       # roms with bad digest
            }
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
            for rom_name, digest in map_digests.items():
                if rom_name not in zip_digests:
                    stats['missing_roms'].setdefault(zip_name, list()).append(rom_name)
                    stats['bad_files'].add(zip_name)
                elif digest != zip_digests[rom_name]:
                    stats['bad_roms'].setdefault(zip_name, list()).append((rom_name,
                                                                           zip_digests[rom_name],
                                                                           digest,)
                                                                         )
                    stats['bad_files'].add(zip_name)
        else:
            stats['missing_files'].append(zip_name)
        cur_rom += 1

    display_stats(stats)

ARGS = parse_args()
ROM_MAP = create_romfile_map(ARGS.dat)
create_romfile_checklist(ROM_MAP, ARGS.set_type)
check_roms(ROM_MAP, ARGS.rom_dir)
